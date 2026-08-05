import asyncio
import logging
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, Message, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)

from config import PDF_PATH, PDF_FILE_ID
from database.crud import has_paid, mark_user_paid, save_phone, pop_pending_payment_by_phone
from keyboards.main import payment_keyboard, community_keyboard
from texts.messages import BUY_OFFER_TEXT, POST_PURCHASE_TEXT

router = Router()
logger = logging.getLogger(__name__)


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


@router.callback_query(F.data == "buy")
async def show_buy_offer(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    if await has_paid(user_id):
        await callback.message.answer("Ты уже получил книгу 📖 Найди её выше в чате.")
        return
    # Сразу к оплате — без промежуточных шагов и без запроса телефона
    await callback.message.answer(BUY_OFFER_TEXT, reply_markup=payment_keyboard(user_id))


@router.callback_query(F.data == "pay_now")
async def pay_now(callback: CallbackQuery) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    if await has_paid(user_id):
        await callback.message.answer("Книга уже отправлена — найди её выше в чате 📖")
        return
    # Прямая ссылка на оплату, без запроса телефона
    await callback.message.answer(
        "💳 Оплата — 350 ₽\n\nНажми «Оплатить» → введи карту — книга придёт сюда автоматически 📖",
        reply_markup=payment_keyboard(user_id),
    )


@router.message(F.contact)
async def got_contact(message: Message, bot: Bot) -> None:
    user_id = message.from_user.id
    phone = message.contact.phone_number
    await save_phone(user_id, phone)
    await message.answer(".", reply_markup=ReplyKeyboardRemove())

    # Проверяем — может уже оплатил пока шёл к этому шагу
    order_id = await pop_pending_payment_by_phone(phone)
    if order_id:
        await mark_user_paid(user_id, tribute_id=order_id)
        await deliver_book(bot, user_id)
        logger.info("Книга доставлена из pending: user=%s phone=%s", user_id, phone)
        return

    if await has_paid(user_id):
        await message.answer("Книга уже отправлена — найди её выше в чате 📖")
        return

    await message.answer(
        "💳 Оплата — 350 ₽\n\nНажми «Оплатить» → введи карту — книга придёт сюда автоматически 📖",
        reply_markup=payment_keyboard(user_id),
    )


@router.callback_query(F.data == "check_payment")
async def check_payment(callback: CallbackQuery, bot: Bot) -> None:
    await callback.answer()
    user_id = callback.from_user.id

    if await has_paid(user_id):
        await callback.message.answer("Оплата подтверждена ✅ Книга уже отправлена — найди её выше в чате 📖")
        return

    # Оплата привязана к tg_id — книга придёт автоматически, телефон не нужен
    await callback.message.answer(
        "Проверяю оплату… Если ты только что оплатил — книга придёт сюда автоматически в течение минуты 📖\n\n"
        "Если через пару минут её нет — напиши @semke_ivan, отправлю вручную."
    )


async def deliver_book(bot: Bot, user_id: int) -> None:
    try:
        # Используем file_id с серверов Telegram (приоритет) или локальный файл
        document = PDF_FILE_ID if PDF_FILE_ID else FSInputFile(PDF_PATH)
        await bot.send_document(
            chat_id=user_id,
            document=document,
            caption="📎 Вот твоя книга. Сохрани её — она никуда не денется.",
        )
        await asyncio.sleep(60)
        await bot.send_message(user_id, POST_PURCHASE_TEXT, reply_markup=community_keyboard())
    except Exception as e:
        logger.error("Ошибка доставки книги user=%s: %s", user_id, e)

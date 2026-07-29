import logging
from aiogram import Router, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, FSInputFile

from config import COVER_PATH
from database.crud import get_or_create_user, has_paid, mark_user_paid, reset_drip
from handlers.payment import deliver_book
from keyboards.main import main_keyboard
from texts.messages import WELCOME_TEXT
from utils.payment_token import verify_token

router = Router()
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    user = message.from_user
    await get_or_create_user(user.id, user.username or "", user.first_name or "")

    # Обработка deep link после оплаты: /start paid_{user_id}_{token}
    args = message.text.split(maxsplit=1)[1] if " " in message.text else ""
    if args.startswith("paid_"):
        await handle_paid_deeplink(message, bot, args)
        return

    if await has_paid(user.id):
        await message.answer("Привет! Ты уже получил книгу 📖\nЕсли потерял — напиши @semke_ivan")
        return

    await reset_drip(user.id)

    if COVER_PATH.exists():
        await message.answer_photo(
            photo=FSInputFile(COVER_PATH),
            caption=WELCOME_TEXT,
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer(WELCOME_TEXT, reply_markup=main_keyboard())


async def handle_paid_deeplink(message: Message, bot: Bot, args: str) -> None:
    """Вызывается когда пользователь вернулся из payform после оплаты."""
    try:
        # args = "paid_{user_id}_{token}"
        parts = args.split("_")  # ["paid", user_id, token]
        if len(parts) != 3:
            raise ValueError("bad format")
        target_user_id = int(parts[1])
        token = parts[2]
    except (ValueError, IndexError):
        logger.warning("Невалидный paid deep link: %s", args)
        return

    # Проверка: токен должен совпадать с user_id из ссылки
    if not verify_token(target_user_id, token):
        logger.warning("Невалидный токен оплаты user=%s", target_user_id)
        await message.answer("❌ Ссылка недействительна. Напиши @semke_ivan")
        return

    # Принимаем оплату только от того пользователя, чей user_id в токене
    if message.from_user.id != target_user_id:
        logger.warning("Чужой paid link: from=%s target=%s", message.from_user.id, target_user_id)
        await message.answer("❌ Эта ссылка не для тебя. Напиши @semke_ivan")
        return

    if await has_paid(target_user_id):
        await message.answer("Книга уже отправлена! Найди её в чате выше 📖")
        return

    await mark_user_paid(target_user_id, tribute_id="payform_redirect")
    logger.info("Оплата подтверждена через deep link user=%s", target_user_id)
    await deliver_book(bot, target_user_id)

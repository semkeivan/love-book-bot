from urllib.parse import urlencode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

PAYFORM_BASE = "https://payform.ru/3cbQXFl/"


def main_keyboard() -> InlineKeyboardMarkup:
    # Два выбора: сразу купить или почитать подробнее на сайте.
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить книгу — 350 ₽", callback_data="buy")],
        [InlineKeyboardButton(text="📖 Подробнее о книге", url="https://god-love-you.bloomcode.net/")],
    ])


def after_question_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Хочу книгу — 350 ₽", callback_data="buy")],
        [InlineKeyboardButton(text="← Посмотреть другие вопросы", callback_data="back_to_main")],
    ])


def buy_offer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Получить книгу — 350 ₽", callback_data="pay_now")],
        [InlineKeyboardButton(text="← Вернуться", callback_data="back_to_main")],
    ])


def payment_keyboard(user_id: int) -> InlineKeyboardMarkup:
    pay_url = f"{PAYFORM_BASE}?{urlencode({'order_num': f'tg_{user_id}'})}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить — 350 ₽", url=pay_url)],
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data="check_payment")],
    ])


def community_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Войти в сообщество", url="https://t.me/semke_youtube")],
    ])


def buy_reminder_keyboard(user_id: int = 0) -> InlineKeyboardMarkup:
    if user_id:
        pay_url = f"{PAYFORM_BASE}?{urlencode({'order_num': f'tg_{user_id}'})}"
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить книгу — 350 ₽", url=pay_url)],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить книгу — 350 ₽", callback_data="buy")],
    ])

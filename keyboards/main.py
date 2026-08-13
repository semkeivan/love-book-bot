from urllib.parse import urlencode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from utils.payment_token import make_token

PAYFORM_BASE = "https://payform.ru/3cbQXFl/"
BOT_USERNAME = "bible_love_bot"
NOTIFY_URL = "https://relearn-whiff-pusher.ngrok-free.dev/payform-webhook"


def build_pay_url(user_id: int) -> str:
    """Ссылка оплаты с двумя независимыми путями доставки:
    - order_num=tg_<id>  → серверное уведомление (webhook) находит покупателя
    - urlSuccess          → после оплаты Prodamus возвращает покупателя в бота
                            по deep-link, который сразу выдаёт книгу (без webhook)
    - urlNotification     → дублируем адрес уведомления прямо в ссылке
    """
    token = make_token(user_id)
    success_url = f"https://t.me/{BOT_USERNAME}?start=paid_{user_id}_{token}"
    params = {
        "order_num": f"tg_{user_id}",
        "urlSuccess": success_url,
        "urlNotification": NOTIFY_URL,
    }
    return f"{PAYFORM_BASE}?{urlencode(params)}"


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
    pay_url = build_pay_url(user_id)
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
        pay_url = build_pay_url(user_id)
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить книгу — 350 ₽", url=pay_url)],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить книгу — 350 ₽", callback_data="buy")],
    ])

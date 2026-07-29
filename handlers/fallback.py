import logging
from aiogram import Router, F, Bot
from aiogram.types import Message

from config import ADMIN_IDS
from database.crud import log_message

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text & ~F.text.startswith("/"))
async def forward_to_admin(message: Message, bot: Bot) -> None:
    user = message.from_user
    if user.id in ADMIN_IDS:
        return
    username = f"@{user.username}" if user.username else "без username"
    await log_message(user.id, user.username or "", user.first_name or "", message.text)
    await bot.send_message(
        ADMIN_IDS[0],
        f"✉️ Сообщение от {user.first_name or '—'} ({username}, id={user.id}):\n\n{message.text}",
    )
    await message.answer("Спасибо! Я передал твой вопрос — скоро отвечу 🙂")

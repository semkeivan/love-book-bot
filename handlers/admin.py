import logging
from aiogram import Router, Bot
from aiogram.filters import Command
from aiogram.types import Message

from config import ADMIN_IDS
from database.crud import get_stats, get_paid_users, get_all_user_ids, has_paid, mark_user_paid, get_unpaid_users, delete_user, get_pending_payments, get_reply_stats
from handlers.payment import deliver_book

router = Router()
logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    total, paid = await get_stats()
    conv = round(paid / total * 100, 1) if total else 0
    await message.answer(
        f"📊 Статистика\n\nВсего: {total}\nКупили: {paid}\nКонверсия: {conv}%"
    )


@router.message(Command("paid_list"))
async def cmd_paid_list(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    users = await get_paid_users()
    if not users:
        await message.answer("Покупок пока нет.")
        return
    lines = [f"• {u['first_name']} (@{u['username']}) — {str(u['paid_at'])[:10]}" for u in users]
    await message.answer("💳 Купившие:\n\n" + "\n".join(lines))


@router.message(Command("mark_paid"))
async def cmd_mark_paid(message: Message, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /mark_paid USER_ID")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("USER_ID должен быть числом.")
        return

    if await has_paid(user_id):
        await message.answer(f"Пользователь {user_id} уже отмечен как оплативший.")
        return

    await mark_user_paid(user_id, tribute_id="manual")
    await deliver_book(bot, user_id)
    await message.answer(f"✅ {user_id} — книга отправлена.")


@router.message(Command("unpaid"))
async def cmd_unpaid(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    users = await get_unpaid_users()
    if not users:
        await message.answer("Все зашедшие — купили 🎉")
        return
    lines = []
    for u in users:
        name = u["first_name"] or "—"
        username = f"@{u['username']}" if u["username"] else "без username"
        date = str(u["joined_at"])[:10]
        lines.append(f"• {name} ({username}) — зашёл {date}, стадия: {u['stage']}")
    await message.answer(f"😴 Не оплатили ({len(users)}):\n\n" + "\n".join(lines))


@router.message(Command("delete_me"))
async def cmd_delete_me(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await delete_user(message.from_user.id)
    await message.answer("✅ Ты удалён из базы. Можешь тестировать /start заново.")


@router.message(Command("delete_user"))
async def cmd_delete_user(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /delete_user USER_ID")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("USER_ID должен быть числом.")
        return
    await delete_user(user_id)
    await message.answer(f"✅ Пользователь {user_id} удалён из базы.")


@router.message(Command("pending"))
async def cmd_pending(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    payments = await get_pending_payments()
    if not payments:
        await message.answer("✅ Подвисших оплат нет.")
        return
    lines = []
    for p in payments:
        lines.append(
            f"• tel: {p['phone']} | email: {p['email'] or '—'} | order: {p['order_id']} | {str(p['created_at'])[:16]}"
        )
    await message.answer(
        f"⚠️ Оплаты без доставки ({len(payments)}):\n\n" + "\n".join(lines) +
        "\n\nЧтобы доставить: /mark_paid USER_ID"
    )


@router.message(Command("replies"))
async def cmd_replies(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    hours = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 48
    replies = await get_reply_stats(hours=hours)
    if not replies:
        await message.answer(f"За последние {hours}ч ответов нет.")
        return
    header = f"📊 Ответы за последние {hours}ч: {len(replies)} шт.\n\n"
    chunks = [header]
    for r in replies:
        uname = f"@{r['username']}" if r['username'] else "без username"
        line = f"• {r['first_name']} ({uname}) [{str(r['received_at'])[:16]}]:\n  {r['text']}\n"
        if sum(len(c) for c in chunks) + len(line) > 3800:
            await message.answer("".join(chunks))
            chunks = []
        chunks.append(line)
    if chunks:
        await message.answer("".join(chunks))


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    text = message.text.removeprefix("/broadcast").strip()
    if not text:
        await message.answer("Формат: /broadcast Текст")
        return
    user_ids = await get_all_user_ids()
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"Рассылка завершена. Отправлено: {sent}, ошибок: {failed}")

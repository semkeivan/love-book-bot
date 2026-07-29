import asyncio
import logging

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import BOT_TOKEN, WEBHOOK_PORT, PUBLIC_URL
from database.models import init_db
from handlers import start, questions, payment, admin, fallback
from scheduler.reminders import setup_scheduler
from webhook.payform import payform_webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

TELEGRAM_WEBHOOK_PATH = "/tg-webhook"


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env")

    init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start.router)
    dp.include_router(questions.router)
    dp.include_router(payment.router)
    dp.include_router(admin.router)
    dp.include_router(fallback.router)

    scheduler = setup_scheduler(bot)
    scheduler.start()

    app = web.Application()
    app["bot"] = bot

    # Payform webhook
    app.router.add_post("/payform-webhook", payform_webhook)

    # Tribute webhook
    try:
        from webhook.tribute import tribute_webhook
        app.router.add_post("/tribute-webhook", tribute_webhook)
    except Exception:
        pass

    # Admin endpoints
    async def admin_unpaid(request: web.Request) -> web.Response:
        import json
        from database.crud import get_unpaid_users
        from config import ADMIN_IDS
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        users = await get_unpaid_users()
        return web.Response(text=json.dumps(users, ensure_ascii=False, default=str), content_type="application/json")

    async def admin_deliver(request: web.Request) -> web.Response:
        from database.crud import has_paid, mark_user_paid
        from handlers.payment import deliver_book
        from config import ADMIN_IDS
        token = request.rel_url.query.get("token", "")
        user_id = request.rel_url.query.get("user_id", "")
        if token != str(ADMIN_IDS[0]) or not user_id:
            return web.Response(status=403, text="forbidden")
        uid = int(user_id)
        already = await has_paid(uid)
        if not already:
            await mark_user_paid(uid, tribute_id="manual")
        await deliver_book(request.app["bot"], uid)
        return web.Response(text=f"ok, delivered to {uid}, already_paid={already}")

    async def admin_all_users(request: web.Request) -> web.Response:
        import json, sqlite3
        from config import ADMIN_IDS, DB_PATH
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT id, username, first_name, phone, stage, paid_at, joined_at FROM users ORDER BY joined_at DESC").fetchall()
        return web.Response(text=json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str), content_type="application/json")

    async def admin_pending(request: web.Request) -> web.Response:
        import json, sqlite3
        from config import ADMIN_IDS, DB_PATH
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM pending_payments ORDER BY created_at DESC").fetchall()
        return web.Response(text=json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str), content_type="application/json")

    async def admin_warmup(request: web.Request) -> web.Response:
        import sqlite3
        from config import ADMIN_IDS, DB_PATH
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT id FROM users WHERE paid_at IS NULL AND id > 0"
            ).fetchall()
        user_ids = [r[0] for r in rows]
        text = (
            "Привет 👋\n\n"
            "Ты заходил в наш бот — значит, что-то тебя задело. Может, вопрос о любви, "
            "который долго не даёт покоя. Или ощущение, что в отношениях что-то идёт не так, а почему — непонятно.\n\n"
            "Мы написали книгу именно для таких моментов. Не теория — живые ответы на то, что болит: "
            "почему любовь уходит, почему мы срываемся на близких, как выйти из круга обид.\n\n"
            "350 ₽ — и она у тебя. Один вечер с книгой может изменить то, "
            "как ты видишь самых важных людей в своей жизни 💛\n\n"
            "Если есть вопросы или сомнения — просто напиши сюда, отвечу 🙂"
        )
        sent, failed = 0, 0
        for uid in user_ids:
            try:
                await request.app["bot"].send_message(uid, text)
                sent += 1
            except Exception:
                failed += 1
        return web.Response(text=f"sent={sent} failed={failed}")

    async def admin_broadcast_photo(request: web.Request) -> web.Response:
        import sqlite3
        from aiogram.types import FSInputFile
        from config import ADMIN_IDS, DB_PATH
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        photo_path = request.rel_url.query.get("photo", "assets/bible_infographic.jpeg")
        caption = request.rel_url.query.get("caption", "")
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("SELECT id FROM users WHERE id > 0").fetchall()
        user_ids = [r[0] for r in rows]
        sent, failed = 0, 0
        file_id = None
        for uid in user_ids:
            try:
                if file_id:
                    await request.app["bot"].send_photo(uid, file_id, caption=caption)
                else:
                    msg = await request.app["bot"].send_photo(
                        uid, FSInputFile(photo_path), caption=caption
                    )
                    file_id = msg.photo[-1].file_id
                sent += 1
            except Exception:
                failed += 1
        return web.Response(text=f"sent={sent} failed={failed}")

    async def admin_campaign(request: web.Request) -> web.Response:
        import sqlite3
        from config import ADMIN_IDS, DB_PATH
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute("SELECT id FROM users WHERE id > 0").fetchall()
        user_ids = [r[0] for r in rows]
        text = (
            "Привет! 👋\n\n"
            "Скажи, успел(а) уже прочитать книгу? Как тебе? Было бы интересно услышать 🙂\n\n"
            "—\n\n"
            "Тут подумал об одной теме, которую мало кто прорабатывает.\n\n"
            "Каждый из нас хочет настоящих, искренних, счастливых отношений. И книга как раз об этом. "
            "Но есть момент, который часто пропускают — в самом начале.\n\n"
            "Когда встречаешь человека: как понять, что он твой? Совпадаете ли вы по ценностям? "
            "Как будете вести себя в сложных ситуациях? Стоит ли вкладываться в эти отношения?\n\n"
            "Думаю собрать список из 100 вопросов — тех, что важно обсудить с партнёром до того, "
            "как принять решение о серьёзных отношениях. Вопросы, которые помогут по-настоящему узнать человека рядом.\n\n"
            "Было бы тебе интересно такое? Обсудил(а) бы со своим партнёром?\n\n"
            "Ответь прямо сюда 👇"
        )
        sent, failed = 0, 0
        for uid in user_ids:
            try:
                await request.app["bot"].send_message(uid, text)
                sent += 1
            except Exception:
                failed += 1
        summary = (
            f"📬 Рассылка завершена.\n\n"
            f"Доставлено: {sent}\n"
            f"Не доставлено (бот заблокирован): {failed}\n"
            f"Прочитано: Telegram не предоставляет эти данные ботам\n\n"
            f"Ответы приходят сюда в реальном времени. "
            f"Статистику ответов смотри командой /replies (за 48ч) или /replies 24 (за 24ч)."
        )
        await request.app["bot"].send_message(ADMIN_IDS[0], summary)
        return web.Response(text=f"sent={sent} failed={failed}")

    app.router.add_get("/admin/unpaid", admin_unpaid)
    app.router.add_get("/admin/deliver", admin_deliver)
    app.router.add_get("/admin/pending", admin_pending)
    app.router.add_get("/admin/users", admin_all_users)
    async def admin_message_log(request: web.Request) -> web.Response:
        import json, sqlite3
        from config import ADMIN_IDS, DB_PATH
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        hours = int(request.rel_url.query.get("hours", 720))
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM message_log WHERE received_at >= datetime('now', ? || ' hours') ORDER BY received_at DESC",
                (f"-{hours}",)
            ).fetchall()
        return web.Response(
            text=json.dumps([dict(r) for r in rows], ensure_ascii=False, default=str),
            content_type="application/json"
        )

    app.router.add_get("/admin/warmup", admin_warmup)
    app.router.add_get("/admin/broadcast_photo", admin_broadcast_photo)
    app.router.add_get("/admin/campaign", admin_campaign)
    app.router.add_get("/admin/message_log", admin_message_log)

    # Telegram webhook
    webhook_url = f"{PUBLIC_URL}{TELEGRAM_WEBHOOK_PATH}"
    if PUBLIC_URL:
        await bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info("Telegram webhook установлен: %s", webhook_url)
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=TELEGRAM_WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
    else:
        logger.warning("PUBLIC_URL не задан — fallback на polling (только для локальной разработки)")

    logger.info("=== WEBHOOK URL для payform.ru: %s/payform-webhook ===", PUBLIC_URL)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()
    logger.info("Бот запущен на порту %s", WEBHOOK_PORT)

    if not PUBLIC_URL:
        # Локальный polling как fallback
        await bot.delete_webhook(drop_pending_updates=True)
        try:
            await dp.start_polling(bot)
        finally:
            scheduler.shutdown()
            await runner.cleanup()
            await bot.session.close()
    else:
        try:
            await asyncio.Event().wait()
        finally:
            scheduler.shutdown()
            await runner.cleanup()
            await bot.set_webhook("")
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

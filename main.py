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
        import json
        from database.crud import get_all_users
        from config import ADMIN_IDS
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        rows = await get_all_users()
        return web.Response(text=json.dumps(rows, ensure_ascii=False, default=str), content_type="application/json")

    async def admin_pending(request: web.Request) -> web.Response:
        import json
        from database.crud import get_pending_payments
        from config import ADMIN_IDS
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        rows = await get_pending_payments()
        return web.Response(text=json.dumps(rows, ensure_ascii=False, default=str), content_type="application/json")

    async def admin_dashboard(request: web.Request) -> web.Response:
        import html as _html
        from database.crud import get_all_users
        from config import ADMIN_IDS
        token = request.rel_url.query.get("token", "")
        if token != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        users = await get_all_users()
        paid = [u for u in users if u.get("paid_at")]
        unpaid = [u for u in users if not u.get("paid_at")]
        total = len(users) or 1

        stage_labels = {
            "asked_q5": "🔥 Дошли до вопроса 5 — почти купили",
            "asked_q4": "Вопрос 4",
            "asked_q3": "Вопрос 3",
            "asked_q2": "Вопрос 2",
            "asked_q1": "Вопрос 1",
            "new": "Только нажали /start — не вовлеклись",
        }
        order = ["asked_q5", "asked_q4", "asked_q3", "asked_q2", "asked_q1", "new"]

        def row(u):
            name = _html.escape(u.get("first_name") or "(без имени)")
            un = ("@" + _html.escape(u["username"])) if u.get("username") else "—"
            ph = _html.escape(u.get("phone") or "—")
            jd = str(u.get("joined_at") or "")[:10]
            return f"<tr><td>{name}</td><td>{un}</td><td>{ph}</td><td>{jd}</td></tr>"

        blocks = []
        from collections import defaultdict
        by_stage = defaultdict(list)
        for u in unpaid:
            by_stage[u.get("stage", "new")].append(u)
        for s in order:
            group = by_stage.get(s)
            if not group:
                continue
            group.sort(key=lambda u: str(u.get("joined_at") or ""), reverse=True)
            rows = "".join(row(u) for u in group)
            blocks.append(
                f'<h3>{stage_labels.get(s, s)} <span class="cnt">{len(group)}</span> '
                f'<a class="btn" href="/admin/warmup?token={token}&stage={s}" '
                f'onclick="return confirm(\'Отправить рассылку {len(group)} чел. на стадии {s}?\')">✉ Рассылка этой группе</a></h3>'
                f'<table><thead><tr><th>Имя</th><th>Username</th><th>Телефон</th><th>Вошёл</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>'
            )
        paid.sort(key=lambda u: str(u.get("paid_at") or ""), reverse=True)
        paid_rows = "".join(
            f"<tr><td>{_html.escape(u.get('first_name') or '')}</td>"
            f"<td>{('@'+_html.escape(u['username'])) if u.get('username') else '—'}</td>"
            f"<td>{str(u.get('paid_at') or '')[:16]}</td></tr>"
            for u in paid
        )
        conv = round(100 * len(paid) / total)
        page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>База лидов — bible_love_bot</title>
<style>
:root{{color-scheme:light dark}}
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:16px;background:#f5f5f7;color:#111}}
@media(prefers-color-scheme:dark){{body{{background:#1c1c1e;color:#eee}}table{{background:#2c2c2e}}th{{background:#333}}}}
h1{{font-size:20px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.card{{background:#fff;border-radius:12px;padding:14px 18px;min-width:120px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
@media(prefers-color-scheme:dark){{.card{{background:#2c2c2e}}}}
.card .n{{font-size:28px;font-weight:700}}
.card .l{{font-size:13px;opacity:.65}}
h3{{margin-top:28px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:16px}}
.cnt{{background:#0a84ff;color:#fff;border-radius:20px;padding:1px 10px;font-size:14px}}
.btn{{font-size:13px;background:#34c759;color:#fff;padding:5px 12px;border-radius:8px;text-decoration:none;font-weight:600}}
table{{border-collapse:collapse;width:100%;background:#fff;border-radius:10px;overflow:hidden;margin-top:8px;font-size:14px}}
th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid rgba(128,128,128,.2)}}
th{{background:#eee;font-size:13px}}
.wrap{{overflow-x:auto}}
</style></head><body>
<h1>📊 База лидов — @bible_love_bot</h1>
<div class="cards">
<div class="card"><div class="n">{len(users)}</div><div class="l">Всего лидов</div></div>
<div class="card"><div class="n">{len(paid)}</div><div class="l">Оплатили</div></div>
<div class="card"><div class="n">{len(unpaid)}</div><div class="l">Не оплатили</div></div>
<div class="card"><div class="n">{conv}%</div><div class="l">Конверсия</div></div>
</div>
<h2>❌ Не оплатили — по стадиям</h2>
<div class="wrap">{''.join(blocks)}</div>
<h2 style="margin-top:32px">✅ Оплатили ({len(paid)})</h2>
<div class="wrap"><table><thead><tr><th>Имя</th><th>Username</th><th>Когда оплатил</th></tr></thead><tbody>{paid_rows}</tbody></table></div>
<p style="opacity:.5;font-size:12px;margin-top:24px">Данные живые, из облачной базы Turso. Обнови страницу — увидишь актуальное.</p>
</body></html>"""
        return web.Response(text=page, content_type="text/html")

    async def admin_warmup(request: web.Request) -> web.Response:
        from database.crud import get_unpaid_users
        from config import ADMIN_IDS
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        stage_filter = request.rel_url.query.get("stage", "")
        unpaid = await get_unpaid_users()
        if stage_filter:
            unpaid = [u for u in unpaid if u.get("stage") == stage_filter]
        user_ids = [u["id"] for u in unpaid if u["id"] > 0]
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
        from aiogram.types import FSInputFile
        from database.crud import get_all_user_ids
        from config import ADMIN_IDS
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        photo_path = request.rel_url.query.get("photo", "assets/bible_infographic.jpeg")
        caption = request.rel_url.query.get("caption", "")
        all_ids = await get_all_user_ids()
        user_ids = [uid for uid in all_ids if uid > 0]
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
        from database.crud import get_all_user_ids
        from config import ADMIN_IDS
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        all_ids = await get_all_user_ids()
        user_ids = [uid for uid in all_ids if uid > 0]
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
    app.router.add_get("/admin/dashboard", admin_dashboard)
    async def admin_message_log(request: web.Request) -> web.Response:
        import json
        from database.crud import get_reply_stats
        from config import ADMIN_IDS
        if request.rel_url.query.get("token", "") != str(ADMIN_IDS[0]):
            return web.Response(status=403, text="forbidden")
        hours = int(request.rel_url.query.get("hours", 720))
        rows = await get_reply_stats(hours=hours)
        return web.Response(
            text=json.dumps(rows, ensure_ascii=False, default=str),
            content_type="application/json"
        )

    app.router.add_get("/admin/warmup", admin_warmup)
    app.router.add_get("/admin/broadcast_photo", admin_broadcast_photo)
    app.router.add_get("/admin/campaign", admin_campaign)
    app.router.add_get("/admin/message_log", admin_message_log)

    async def health(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/health", health)

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

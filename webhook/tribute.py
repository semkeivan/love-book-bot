"""
Tribute webhook endpoint.

В панели Tribute укажи URL: http://YOUR_SERVER:8080/tribute-webhook

Tribute отправит POST с JSON:
{
  "event": "payment.succeeded",
  "user_id": "telegram_user_id",   // если есть
  "order_id": "...",
  "amount": 300
}

Формат может отличаться — проверь в документации Tribute и при необходимости
адаптируй функцию parse_tribute_payload ниже.
"""

import hashlib
import hmac
import json
import logging
from aiohttp import web

from config import TRIBUTE_WEBHOOK_SECRET
from database.crud import has_paid, mark_user_paid
from handlers.payment import deliver_book

logger = logging.getLogger(__name__)


def verify_signature(body: bytes, signature: str) -> bool:
    if not TRIBUTE_WEBHOOK_SECRET:
        return True  # если секрет не задан — пропускаем проверку
    expected = hmac.new(
        TRIBUTE_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def parse_tribute_payload(data: dict) -> tuple:
    """Извлечь telegram user_id и tribute order_id из payload Tribute."""
    # Tribute передаёт telegram_user_id в поле buyer.telegram_id или user_id
    user_id = None
    for key in ("telegram_user_id", "user_id", "telegram_id"):
        val = data.get(key) or (data.get("buyer") or {}).get(key)
        if val:
            try:
                user_id = int(val)
                break
            except (ValueError, TypeError):
                pass

    order_id = str(data.get("order_id") or data.get("payment_id") or "")
    return user_id, order_id


async def tribute_webhook(request: web.Request) -> web.Response:
    body = await request.read()
    signature = request.headers.get("X-Tribute-Signature", "")

    if not verify_signature(body, signature):
        logger.warning("Invalid Tribute webhook signature")
        return web.Response(status=403, text="Forbidden")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return web.Response(status=400, text="Bad JSON")

    event = data.get("event", "")
    logger.info("Tribute webhook: event=%s", event)

    if event not in ("payment.succeeded", "order.paid", "purchase.completed"):
        return web.Response(text="ok")

    user_id, order_id = parse_tribute_payload(data)
    if not user_id:
        logger.warning("Tribute webhook: no telegram user_id in payload: %s", data)
        return web.Response(text="ok")

    if not has_paid(user_id):
        mark_user_paid(user_id, tribute_id=order_id)
        bot = request.app["bot"]
        await deliver_book(bot, user_id)
        logger.info("Book delivered to user %s after Tribute payment", user_id)

    return web.Response(text="ok")


def create_web_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/tribute-webhook", tribute_webhook)
    return app

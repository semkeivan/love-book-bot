import json
import logging
from aiohttp import web

from database.crud import has_paid, mark_user_paid, get_user_id_by_phone, save_pending_payment
from handlers.payment import deliver_book

logger = logging.getLogger(__name__)


async def payform_webhook(request: web.Request) -> web.Response:
    try:
        # Продамус шлёт уведомления как multipart/form-data — request.post()
        # разбирает и multipart, и urlencoded, в отличие от ручного parse_qs.
        data = await request.post()
        logger.info("Payform webhook: status=%s phone=%s email=%s order_id=%s order_num=%s",
                    data.get("payment_status"), data.get("customer_phone"),
                    data.get("customer_email"), data.get("order_id"), data.get("order_num"))
        # Фиксируем ВСЕ поля уведомления в БД (для диагностики — видно, что реально шлёт Prodamus)
        try:
            from database.crud import log_message
            full = {k: str(data.get(k)) for k in data.keys()}
            await log_message(0, "PRODAMUS_WEBHOOK", "", json.dumps(full, ensure_ascii=False)[:3000])
        except Exception:
            pass
    except Exception as e:
        logger.error("Webhook parse error: %s", e)
        return web.Response(text="ok")

    if data.get("payment_status") != "success":
        return web.Response(text="ok")

    phone = data.get("customer_phone", "")
    order_num = data.get("order_num", "")  # формат: tg_<user_id>
    order_id = data.get("order_id", "")

    user_id = None

    # 1) Самый надёжный способ — кастомный параметр _param_tgid (Prodamus не подменяет его)
    tgid = data.get("_param_tgid") or data.get("param_tgid")
    if tgid:
        try:
            user_id = int(str(tgid).strip())
            logger.info("user_id из _param_tgid: %s", user_id)
        except (ValueError, TypeError):
            pass

    # 2) Запасной — из order_num вида tg_<id>
    if not user_id and order_num.startswith("tg_"):
        try:
            user_id = int(order_num.split("_", 1)[1])
            logger.info("user_id из order_num: %s", user_id)
        except (ValueError, IndexError):
            pass

    # 3) Фолбэк: ищем по номеру телефона
    if not user_id and phone:
        user_id = await get_user_id_by_phone(phone)
        if user_id:
            logger.info("user_id по телефону: %s phone=%s", user_id, phone)

    if user_id:
        if not await has_paid(user_id):
            await mark_user_paid(user_id, tribute_id=order_id or order_num)
            bot = request.app["bot"]
            await deliver_book(bot, user_id)
            logger.info("Книга отправлена user=%s", user_id)
        else:
            logger.info("Повторная оплата user=%s — игнорируем", user_id)
    else:
        # user_id не найден — сохраняем в pending, доставим когда придёт в бот
        email = data.get("customer_email", "")
        await save_pending_payment(phone, email, order_id)
        logger.info("Оплата в pending: phone=%s email=%s order_id=%s", phone, email, order_id)
        # Моментально уведомляем админа — чтобы оплата не потерялась
        try:
            from config import ADMIN_IDS
            if ADMIN_IDS:
                await request.app["bot"].send_message(
                    ADMIN_IDS[0],
                    "💰 Пришла ОПЛАТА, но бот не смог опознать покупателя автоматически.\n\n"
                    f"Телефон: {phone or '—'}\nПочта: {email or '—'}\nЗаказ: {order_id}\n\n"
                    "Обычно это тот, кто только что был в боте. Как он нажмёт «✅ Я оплатил» — "
                    "книга уйдёт сама. Либо пришли мне его @username — выдам вручную.",
                )
        except Exception as e:
            logger.warning("Не смог уведомить админа о pending-оплате: %s", e)

    return web.Response(text="ok")

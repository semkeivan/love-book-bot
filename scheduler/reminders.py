import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from config import ADMIN_IDS
from database.crud import get_drip_pending, advance_drip, get_funnel_stats
from keyboards.main import buy_reminder_keyboard
from texts.messages import DRIP_2H, REMINDER_24H, REMINDER_72H, DRIP_7D

logger = logging.getLogger(__name__)

DRIP_STEPS = [
    (0, 2,    1, DRIP_2H,      True),
    (1, 24,   2, REMINDER_24H, True),
    (2, 72,   3, REMINDER_72H, True),
    (3, 168,  4, DRIP_7D,      True),
]


def setup_scheduler(bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    @scheduler.scheduled_job(IntervalTrigger(hours=1))
    async def send_drip():
        for step, min_hours, next_step, text, with_kb in DRIP_STEPS:
            users = await get_drip_pending(step=step, min_hours=min_hours)
            for user in users:
                uid = user["id"]
                try:
                    kb = buy_reminder_keyboard(uid) if with_kb else None
                    await bot.send_message(uid, text, reply_markup=kb)
                    await advance_drip(uid, next_step)
                    logger.info("Drip step %s → %s sent to user=%s", step, next_step, uid)
                except Exception as e:
                    logger.warning("Drip step %s user=%s: %s", step, uid, e)

    # Ежедневный отчёт в 9:00 по Москве (6:00 UTC)
    @scheduler.scheduled_job(CronTrigger(hour=6, minute=0, timezone="UTC"))
    async def daily_report():
        if not ADMIN_IDS:
            return
        try:
            stats = await get_funnel_stats()
            total = stats["total"]
            paid = stats["paid"]
            unpaid = total - paid
            conv = round(paid / total * 100, 1) if total else 0
            stage_lines = "\n".join(
                f"  • {s['stage']}: {s['cnt']}" for s in stats["stages"]
            ) or "  нет данных"
            text = (
                f"📊 <b>Ежедневный отчёт</b>\n\n"
                f"👥 Всего пользователей: <b>{total}</b>\n"
                f"💰 Оплатили: <b>{paid}</b>\n"
                f"🔄 В воронке (не оплатили): <b>{unpaid}</b>\n"
                f"📈 Конверсия: <b>{conv}%</b>\n\n"
                f"Новых сегодня: {stats['new_today']}  |  Оплат сегодня: {stats['paid_today']}\n\n"
                f"Стадии неоплативших:\n{stage_lines}"
            )
            await bot.send_message(ADMIN_IDS[0], text, parse_mode="HTML")
        except Exception as e:
            logger.error("daily_report error: %s", e)

    return scheduler

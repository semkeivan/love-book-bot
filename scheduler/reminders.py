import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database.crud import get_drip_pending, advance_drip
from keyboards.main import buy_reminder_keyboard
from texts.messages import DRIP_2H, REMINDER_24H, REMINDER_72H, DRIP_7D

logger = logging.getLogger(__name__)

# Шаги цепочки: (текущий step, часов от drip_started_at, следующий step, текст, нужна ли кнопка оплаты)
DRIP_STEPS = [
    (0, 2,    1, DRIP_2H,      True),
    (1, 24,   2, REMINDER_24H, True),
    (2, 72,   3, REMINDER_72H, True),
    (3, 168,  4, DRIP_7D,      True),   # 168ч = 7 дней
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

    return scheduler

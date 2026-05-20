from __future__ import annotations

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.agents.content_agent import PostSlot
from src.agents.orchestrator import Orchestrator
from src.config.settings import Settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Maps (hour, minute) → PostSlot
DAILY_SCHEDULE: list[tuple[int, int, PostSlot]] = [
    (7, 0, PostSlot.MORNING_BRIEF),
    (10, 0, PostSlot.TECHNICAL_DEEP_DIVE),
    (15, 0, PostSlot.VISUAL_SHOWCASE),
    (22, 0, PostSlot.EVENING_BLOG),
]


def _make_job(orchestrator: Orchestrator, slot: PostSlot):
    def job():
        logger.info(f"Scheduler triggered: {slot.value}")
        orchestrator.run_slot(slot)
    job.__name__ = f"job_{slot.value}"
    return job


def build_scheduler(settings: Settings) -> BlockingScheduler:
    tz = pytz.timezone(settings.timezone)
    orchestrator = Orchestrator(settings)
    scheduler = BlockingScheduler(timezone=tz)

    for hour, minute, slot in DAILY_SCHEDULE:
        scheduler.add_job(
            _make_job(orchestrator, slot),
            trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
            id=f"slot_{slot.value}",
            name=f"Daily {hour:02d}:{minute:02d} – {slot.value}",
            max_instances=1,
            coalesce=True,
        )
        logger.info(f"Scheduled [{slot.value}] at {hour:02d}:{minute:02d} {settings.timezone}")

    return scheduler

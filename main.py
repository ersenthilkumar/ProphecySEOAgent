#!/usr/bin/env python3
"""
Social Media Agent – reads tech trends and publishes posts daily at
07:00, 10:00, 15:00, and 22:00 (timezone from .env TIMEZONE).

Usage:
  python main.py               – start the scheduler daemon
  python main.py --run-now morning_brief
  python main.py --run-now technical_deep_dive
  python main.py --run-now visual_showcase
  python main.py --run-now evening_blog
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.config.settings import get_settings
from src.agents.content_agent import PostSlot
from src.agents.orchestrator import Orchestrator
from src.scheduler.scheduler import build_scheduler
from src.utils.logger import get_logger

logger = get_logger("main")


def main() -> None:
    parser = argparse.ArgumentParser(description="Social Media Trend Agent")
    parser.add_argument(
        "--run-now",
        choices=[s.value for s in PostSlot],
        metavar="SLOT",
        help="Run a specific slot immediately instead of starting the scheduler",
    )
    args = parser.parse_args()

    settings = get_settings()

    # Ensure output directories exist
    Path(settings.images_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.blogs_dir).mkdir(parents=True, exist_ok=True)

    if args.run_now:
        slot = PostSlot(args.run_now)
        logger.info(f"Running slot immediately: [bold]{slot.value}[/bold]")
        orchestrator = Orchestrator(settings)
        orchestrator.run_slot(slot)
        return

    # Start blocking scheduler daemon
    logger.info("[bold cyan]Social Media Agent starting…[/bold cyan]")
    scheduler = build_scheduler(settings)
    logger.info("[green]Scheduler running. Press Ctrl+C to stop.[/green]")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down scheduler")
        scheduler.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()

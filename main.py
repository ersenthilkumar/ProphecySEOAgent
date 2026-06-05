#!/usr/bin/env python3
"""
Social Media Agent – reads tech trends and publishes posts daily at
07:00, 10:00, 15:00, and 22:00 (timezone from .env TIMEZONE).

Usage:
  python main.py                                      – start the scheduler daemon
  python main.py --run-now morning_brief              – run slot (interactive topic selection)
  python main.py --run-now technical_deep_dive        – run slot (interactive topic selection)
  python main.py --run-now technical_deep_dive --topic 4  – run slot using topic #4
"""

import argparse
import sys
from pathlib import Path

# Force UTF-8 for all console/file I/O on Windows (default is CP1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    parser.add_argument(
        "--topic",
        type=int,
        metavar="N",
        help="Use trend topic number N instead of interactive selection (requires --run-now)",
    )
    parser.add_argument(
        "--list-topics",
        action="store_true",
        help="Fetch and display trending topics, then exit without generating content",
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        help="Search all sources for articles on a specific topic instead of using trending feed",
    )
    args = parser.parse_args()

    settings = get_settings()

    # Ensure output directories exist
    Path(settings.images_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.blogs_dir).mkdir(parents=True, exist_ok=True)

    if args.list_topics:
        from src.agents.trend_agent import TrendAgent
        agent = TrendAgent(get_settings())
        report = agent.search(args.search) if args.search else agent.fetch()
        sep = "─" * 60
        header = f"TOPICS FOR: {args.search}" if args.search else "TRENDING TOPICS"
        print(f"\n{sep}\n{header}\n{sep}")
        for i, t in enumerate(report.trends, 1):
            score_str = f"  (score: {t.score:.0f})" if t.score else ""
            print(f"  {i:2}. [{t.source}] {t.title}{score_str}")
        print(sep)
        return

    if args.run_now:
        slot = PostSlot(args.run_now)
        logger.info(f"Running slot immediately: [bold]{slot.value}[/bold]")
        orchestrator = Orchestrator(settings)
        orchestrator.run_slot(slot, topic_num=args.topic, search_query=args.search)
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

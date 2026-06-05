from __future__ import annotations

import os
import re
import time
from datetime import datetime
from pathlib import Path

from src.agents.trend_agent import TrendAgent, TrendReport
from src.agents.content_agent import ContentAgent, GeneratedPost, PostSlot
from src.agents.image_agent import ImageAgent
from src.config.settings import Settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class Orchestrator:
    """Coordinates trend reading → content generation → image generation → posting."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.trend_agent = TrendAgent(settings)
        self.content_agent = ContentAgent(settings)
        self.image_agent = ImageAgent(settings)

        # Import here to avoid circular at module level
        from src.social.manager import SocialManager
        self.social_manager = SocialManager(settings)

        Path(settings.blogs_dir).mkdir(parents=True, exist_ok=True)

    def _save_blog(self, post: GeneratedPost) -> str | None:
        if not post.blog_content:
            return None
        raw = post.blog_title if post.blog_title else "blog"
        # Strip URLs, then replace anything that isn't alphanumeric/hyphen with _
        raw = re.sub(r'https?://\S+', '', raw)
        safe_title = re.sub(r'[^\w\-]', '_', raw).strip('_')[:50]
        safe_title = re.sub(r'_+', '_', safe_title) or "blog"
        timestamp = int(time.time())
        filename = f"{safe_title}_{timestamp}.md"
        path = os.path.join(self.settings.blogs_dir, filename)
        content = f"# {post.blog_title}\n\n{post.blog_content}"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Blog saved: {path}")
        return path

    def _select_topic(self, report: TrendReport) -> str | None:
        sep = "─" * 60
        print(f"\n{sep}")
        print("TRENDING TOPICS")
        print(sep)
        for i, trend in enumerate(report.trends, 1):
            score_str = f"  (score: {trend.score:.0f})" if trend.score else ""
            print(f"  {i:2}. [{trend.source}] {trend.title}{score_str}")
        print(sep)
        try:
            raw = input("\nChoose a topic number (or press Enter to let Claude decide): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not raw:
            return None
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(report.trends):
                chosen = report.trends[idx].title
                logger.info(f"Selected topic: [bold]{chosen}[/bold]")
                return chosen
        except ValueError:
            pass
        logger.warning("Invalid selection — Claude will pick the most relevant topic")
        return None

    def _approve(self, post: GeneratedPost) -> bool:
        sep = "─" * 60
        print(f"\n{sep}")
        print(f"TOPIC : {post.topic}")
        print(f"SLOT  : {post.slot.value}")
        print(sep)
        print(post.linkedin_full)
        print(sep)
        try:
            answer = input("\nPublish this post? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        return answer in ("y", "yes")

    def run_slot(
        self,
        slot: PostSlot,
        topic_num: int | None = None,
        search_query: str | None = None,
    ) -> None:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[bold green]─── Starting slot: {slot.value} at {started_at} ───[/bold green]")

        # 1. Fetch or search trends
        try:
            if search_query:
                trend_report: TrendReport = self.trend_agent.search(search_query)
            else:
                trend_report: TrendReport = self.trend_agent.fetch()
        except Exception as exc:
            logger.error(f"Trend fetch failed: {exc}")
            return

        # 2. Topic selection: --topic N pins a specific article; otherwise Claude decides
        selected_topic: str | None = None
        if topic_num is not None:
            idx = topic_num - 1
            if 0 <= idx < len(trend_report.trends):
                selected_topic = trend_report.trends[idx].title
                logger.info(f"Using topic {topic_num}: [bold]{selected_topic}[/bold]")
            else:
                logger.warning(
                    f"--topic {topic_num} out of range (1-{len(trend_report.trends)}) — Claude will pick"
                )

        # 3. Generate content via Claude
        try:
            post: GeneratedPost = self.content_agent.generate(trend_report, slot, selected_topic)
        except Exception as exc:
            logger.error(f"Content generation failed: {exc}")
            return

        # 4. Generate image via DALL-E 3
        try:
            image_path = self.image_agent.generate(post.image_prompt, post.topic)
            post.image_path = image_path
        except Exception as exc:
            logger.warning(f"Image generation failed (continuing without image): {exc}")

        # 5. Save blog if evening slot
        blog_path = self._save_blog(post)
        if blog_path:
            post.linkedin_content += f"\n\n[Full article: {os.path.basename(blog_path)}]"

        # 6. Optional manual approval before publishing
        if self.settings.require_approval and not self._approve(post):
            logger.info("Post skipped — not approved for publishing")
            return

        # 7. Post to all configured social platforms
        results = self.social_manager.publish(post)
        for platform, success in results.items():
            status = "[green]OK[/green]" if success else "[red]FAILED[/red]"
            logger.info(f"  {platform}: {status}")

        logger.info(f"[bold green]─── Slot {slot.value} complete ───[/bold green]\n")

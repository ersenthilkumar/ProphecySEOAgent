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

    def run_slot(self, slot: PostSlot) -> None:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[bold green]─── Starting slot: {slot.value} at {started_at} ───[/bold green]")

        # 1. Fetch trends
        try:
            trend_report: TrendReport = self.trend_agent.fetch()
        except Exception as exc:
            logger.error(f"Trend fetch failed: {exc}")
            return

        # 2. Generate content via Claude
        try:
            post: GeneratedPost = self.content_agent.generate(trend_report, slot)
        except Exception as exc:
            logger.error(f"Content generation failed: {exc}")
            return

        # 3. Generate image via DALL-E 3
        try:
            image_path = self.image_agent.generate(post.image_prompt, post.topic)
            post.image_path = image_path
        except Exception as exc:
            logger.warning(f"Image generation failed (continuing without image): {exc}")

        # 4. Save blog if evening slot
        blog_path = self._save_blog(post)
        if blog_path:
            # Append blog file path as a note in LinkedIn content
            post.linkedin_content += f"\n\n[Full article: {os.path.basename(blog_path)}]"

        # 5. Post to all configured social platforms
        results = self.social_manager.publish(post)
        for platform, success in results.items():
            status = "[green]OK[/green]" if success else "[red]FAILED[/red]"
            logger.info(f"  {platform}: {status}")

        logger.info(f"[bold green]─── Slot {slot.value} complete ───[/bold green]\n")

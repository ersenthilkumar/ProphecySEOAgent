from __future__ import annotations

from src.agents.content_agent import GeneratedPost
from src.config.settings import Settings
from src.social.base import BasePlatform
from src.social.linkedin import LinkedInPlatform
from src.social.twitter import TwitterPlatform
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _build_linkedin_platforms(settings: Settings) -> list[LinkedInPlatform]:
    """Return 0-2 LinkedInPlatform instances based on LINKEDIN_POST_AS."""
    if not settings.linkedin_enabled:
        return []

    mode = settings.linkedin_post_as.strip().lower()
    platforms: list[LinkedInPlatform] = []

    if mode in ("personal", "both"):
        platforms.append(
            LinkedInPlatform(
                settings,
                author_urn=settings.linkedin_author_id,
                label="LinkedIn (Personal)",
            )
        )

    if mode in ("organization", "both"):
        if not settings.linkedin_org_id:
            logger.warning(
                "LINKEDIN_POST_AS=%s but LINKEDIN_ORG_ID is not set — skipping org post",
                mode,
            )
        else:
            org_urn = f"urn:li:organization:{settings.linkedin_org_id.strip()}"
            platforms.append(
                LinkedInPlatform(
                    settings,
                    author_urn=org_urn,
                    label="LinkedIn (Organization)",
                )
            )

    return platforms


class SocialManager:
    """Publishes a GeneratedPost to all configured social platforms.

    Controlled by LINKEDIN_POST_AS in .env:
      personal      – personal profile only  (default)
      organization  – company page only
      both          – personal profile + company page
    """

    def __init__(self, settings: Settings) -> None:
        self.platforms: list[BasePlatform] = [
            TwitterPlatform(settings),
            *_build_linkedin_platforms(settings),
        ]
        active = [p.name for p in self.platforms if p.is_configured()]
        logger.info(f"Active social platforms: {active or ['none – check .env']}")

    def publish(self, post: GeneratedPost) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for platform in self.platforms:
            if platform.is_configured():
                results[platform.name] = platform.post(post)
            else:
                logger.debug(f"Skipping unconfigured platform: {platform.name}")
        return results

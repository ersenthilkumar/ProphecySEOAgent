from __future__ import annotations

import tweepy

from src.agents.content_agent import GeneratedPost
from src.config.settings import Settings
from src.social.base import BasePlatform
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TwitterPlatform(BasePlatform):
    name = "Twitter/X"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: tweepy.Client | None = None
        self._api: tweepy.API | None = None
        if settings.twitter_enabled:
            self._setup()

    def _setup(self) -> None:
        auth = tweepy.OAuth1UserHandler(
            self.settings.twitter_api_key,
            self.settings.twitter_api_secret,
            self.settings.twitter_access_token,
            self.settings.twitter_access_token_secret,
        )
        self._api = tweepy.API(auth)
        self._client = tweepy.Client(
            bearer_token=self.settings.twitter_bearer_token,
            consumer_key=self.settings.twitter_api_key,
            consumer_secret=self.settings.twitter_api_secret,
            access_token=self.settings.twitter_access_token,
            access_token_secret=self.settings.twitter_access_token_secret,
        )
        logger.info("Twitter client initialised")

    def is_configured(self) -> bool:
        return self.settings.twitter_enabled and self._client is not None

    def post(self, post: GeneratedPost) -> bool:
        if not self.is_configured():
            logger.warning("Twitter not configured – skipping")
            return False
        try:
            media_ids: list[str] = []
            if post.image_path and self._api:
                media = self._api.media_upload(post.image_path)
                media_ids.append(str(media.media_id))
                logger.info(f"Twitter: uploaded media {media.media_id}")

            kwargs: dict = {"text": post.twitter_full}
            if media_ids:
                kwargs["media_ids"] = media_ids

            self._client.create_tweet(**kwargs)
            logger.info("Twitter: tweet published successfully")
            return True
        except Exception as exc:
            logger.error(f"Twitter post failed: {exc}")
            return False

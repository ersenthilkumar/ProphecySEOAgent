import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",  # strips UTF-8 BOM added by Windows editors/tools
        case_sensitive=False,
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-opus-4-7"

    # OpenAI (DALL-E) — optional; image generation is skipped if not set
    openai_api_key: str = ""

    # Twitter/X
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""
    twitter_bearer_token: str = ""

    # LinkedIn
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""  # Primary Client Secret from LinkedIn Developer Portal
    linkedin_access_token: str = ""
    linkedin_author_id: str = ""      # e.g. urn:li:person:ABC123  (personal profile)
    linkedin_org_id: str = ""         # numeric company page ID, e.g. 76838386
    linkedin_post_as: str = "personal"  # personal | organization | both

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "SocialMediaAgent/1.0"

    # App
    timezone: str = "America/New_York"
    tech_focus: str = (
        "software development, AI/ML, cloud computing, DevOps, web development, cybersecurity"
    )
    output_dir: str = "./output"
    require_approval: bool = False  # if true, show preview and prompt before publishing

    @property
    def images_dir(self) -> str:
        return os.path.join(self.output_dir, "images")

    @property
    def blogs_dir(self) -> str:
        return os.path.join(self.output_dir, "blogs")

    @property
    def twitter_enabled(self) -> bool:
        return bool(self.twitter_api_key and self.twitter_bearer_token)

    @property
    def linkedin_enabled(self) -> bool:
        return bool(self.linkedin_access_token and self.linkedin_author_id)

    @property
    def reddit_enabled(self) -> bool:
        return bool(self.reddit_client_id and self.reddit_client_secret)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

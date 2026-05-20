from __future__ import annotations

from abc import ABC, abstractmethod
from src.agents.content_agent import GeneratedPost


class BasePlatform(ABC):
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def post(self, post: GeneratedPost) -> bool:
        """Publish the post. Returns True on success."""
        ...

from __future__ import annotations

import os
import re
import time
import requests
from pathlib import Path

from openai import OpenAI

from src.config.settings import Settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ImageAgent:
    """Generates post images via OpenAI DALL-E 3 and saves them locally."""

    STYLE_PREFIX = (
        "Professional tech illustration, clean modern design, "
        "dark background with vibrant accent colours (blue/cyan/purple gradient), "
        "futuristic aesthetic, high contrast, 4K quality. "
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key)
        Path(settings.images_dir).mkdir(parents=True, exist_ok=True)

    def generate(self, prompt: str, filename_hint: str = "") -> str:
        """Generate an image from *prompt* and return the local file path."""
        full_prompt = f"{self.STYLE_PREFIX}{prompt}"
        logger.info(f"Generating image: {prompt[:80]}...")

        response = self.client.images.generate(
            model="dall-e-3",
            prompt=full_prompt,
            size="1792x1024",
            quality="standard",
            n=1,
        )

        image_url = response.data[0].url
        revised_prompt = response.data[0].revised_prompt
        logger.info(f"DALL-E revised prompt: {revised_prompt[:80]}...")

        # Download and save
        safe_hint = re.sub(r"[^\w\-]", "_", filename_hint)[:40] if filename_hint else "post"
        timestamp = int(time.time())
        filename = f"{safe_hint}_{timestamp}.png"
        file_path = os.path.join(self.settings.images_dir, filename)

        img_data = requests.get(image_url, timeout=30).content
        with open(file_path, "wb") as f:
            f.write(img_data)

        logger.info(f"Image saved: {file_path}")
        return file_path

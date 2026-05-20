from __future__ import annotations

import base64
import mimetypes
import os
import time

import requests

from src.agents.content_agent import GeneratedPost
from src.config.settings import Settings
from src.social.base import BasePlatform
from src.utils.logger import get_logger

logger = get_logger(__name__)

LI_API = "https://api.linkedin.com/v2"
LI_ASSETS_API = "https://api.linkedin.com/v2/assets"
LI_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"


class LinkedInPlatform(BasePlatform):

    def __init__(self, settings: Settings, author_urn: str, label: str = "LinkedIn") -> None:
        self.settings = settings
        self.name = label
        self._author_urn = author_urn
        self._access_token: str = settings.linkedin_access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def refresh_access_token(self, refresh_token: str) -> bool:
        """Exchange a refresh token for a new access token using the client credentials.

        LinkedIn access tokens expire after 60 days; refresh tokens last 1 year.
        Call this when a 401 is returned and store the new token in .env manually,
        or pass it programmatically before the scheduler starts.
        """
        if not (self.settings.linkedin_client_id and self.settings.linkedin_client_secret):
            logger.error("Cannot refresh token: LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET not set")
            return False
        try:
            resp = requests.post(
                LI_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.settings.linkedin_client_id,
                    "client_secret": self.settings.linkedin_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            resp.raise_for_status()
            new_token = resp.json()["access_token"]
            self._access_token = new_token
            logger.info("LinkedIn access token refreshed successfully")
            return True
        except Exception as exc:
            logger.error(f"LinkedIn token refresh failed: {exc}")
            return False

    def is_configured(self) -> bool:
        return self.settings.linkedin_enabled

    # ── Image upload ──────────────────────────────────────────────────────────

    def _register_upload(self) -> tuple[str, str]:
        """Register an image upload with LinkedIn. Returns (upload_url, asset_urn)."""
        payload = {
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": self._author_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
            }
        }
        resp = requests.post(
            f"{LI_ASSETS_API}?action=registerUpload",
            json=payload,
            headers=self._headers(),
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()["value"]
        upload_url = data["uploadMechanism"][
            "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
        ]["uploadUrl"]
        asset_urn = data["asset"]
        return upload_url, asset_urn

    def _upload_image(self, file_path: str) -> str:
        """Upload image file and return the asset URN."""
        upload_url, asset_urn = self._register_upload()
        mime, _ = mimetypes.guess_type(file_path)
        with open(file_path, "rb") as f:
            img_bytes = f.read()
        upload_resp = requests.put(
            upload_url,
            data=img_bytes,
            headers={
                "Authorization": f"Bearer {self.settings.linkedin_access_token}",
                "Content-Type": mime or "image/png",
            },
            timeout=60,
        )
        upload_resp.raise_for_status()
        logger.info(f"LinkedIn: image uploaded, asset={asset_urn}")
        return asset_urn

    # ── Post creation ─────────────────────────────────────────────────────────

    def _do_post(self, payload: dict) -> str:
        """Send the ugcPost request with automatic retry on 429 / 5xx."""
        delays = [60, 120, 300]  # seconds between retries (1m, 2m, 5m)
        for attempt, delay in enumerate(delays, 1):
            resp = requests.post(
                f"{LI_API}/ugcPosts",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", delay))
                logger.warning(
                    f"LinkedIn 429 rate-limited — waiting {retry_after}s "
                    f"(attempt {attempt}/{len(delays)})"
                )
                time.sleep(retry_after)
                continue
            if resp.status_code >= 500 and attempt < len(delays):
                logger.warning(f"LinkedIn {resp.status_code} — retrying in {delay}s")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.headers.get("x-restli-id", "n/a")
        resp.raise_for_status()  # final attempt already raised above; belt-and-suspenders
        return "n/a"

    def post(self, generated: GeneratedPost) -> bool:
        if not self.is_configured():
            logger.warning("LinkedIn not configured – skipping")
            return False
        try:
            asset_urn: str | None = None
            if generated.image_path and os.path.isfile(generated.image_path):
                asset_urn = self._upload_image(generated.image_path)

            share_content: dict = {
                "shareCommentary": {"text": generated.linkedin_full},
                "shareMediaCategory": "IMAGE" if asset_urn else "NONE",
            }
            if asset_urn:
                share_content["media"] = [
                    {
                        "status": "READY",
                        "description": {"text": generated.topic},
                        "media": asset_urn,
                        "title": {"text": generated.topic},
                    }
                ]

            payload = {
                "author": self._author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": share_content
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                },
            }
            logger.info(f"LinkedIn: posting as {self._author_urn} [{self.name}]")

            post_id = self._do_post(payload)
            logger.info(f"LinkedIn: post published (id={post_id})")
            return True
        except Exception as exc:
            logger.error(f"LinkedIn post failed: {exc}")
            return False

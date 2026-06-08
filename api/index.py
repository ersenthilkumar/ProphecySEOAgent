from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

# Ensure the project root is on the path so src/ imports work from Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

_JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
_TOKEN_EXPIRE_HOURS = 24
_security = HTTPBearer()

from src.config.settings import Settings
from src.agents.trend_agent import TrendAgent
from src.agents.content_agent import ContentAgent, GeneratedPost, PostSlot
from src.social.linkedin import LinkedInPlatform

app = FastAPI(title="Social Media Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _get_users() -> dict[str, str]:
    """Parse APP_USERS env var: 'user1:pass1,user2:pass2'"""
    raw = os.getenv("APP_USERS", "")
    users: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            u, p = pair.split(":", 1)
            users[u.strip()] = p.strip()
    return users

def _create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")

def _verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    try:
        payload = jwt.decode(
            credentials.credentials, _JWT_SECRET, algorithms=["HS256"]
        )
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token — please log in again")


# ── Request / Response models ──────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class GenerateRequest(BaseModel):
    slot: str
    topic_title: str | None = None
    search_query: str | None = None


class PublishRequest(BaseModel):
    topic: str
    linkedin_content: str
    hashtags: list[str]
    slot: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_slot(slot_str: str) -> PostSlot:
    try:
        return PostSlot(slot_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown slot: {slot_str!r}. "
                            f"Valid values: {[s.value for s in PostSlot]}")


def _source_label(source: str) -> str:
    """Normalise raw source strings to short badge labels."""
    s = source.lower()
    if "hackernews" in s or "hacker news" in s:
        return "HN"
    if "dev.to" in s or "devto" in s:
        return "DEV"
    if "reddit" in s:
        return "Reddit"
    if "google" in s:
        return "Google"
    return source[:6]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/api/login")
def login(req: LoginRequest):
    raw = os.getenv("APP_USERS", "")
    if not raw:
        raise HTTPException(status_code=503, detail=f"APP_USERS is empty (len=0)")
    users = _get_users()
    if not users:
        raise HTTPException(status_code=503, detail=f"APP_USERS parse failed. len={len(raw)}, repr={repr(raw[:30])}")
    if req.username not in users or users[req.username] != req.password:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": _create_token(req.username), "username": req.username}


@app.get("/api/me")
def me(user: str = Depends(_verify_token)):
    return {"username": user}


@app.get("/api/topics")
def get_topics(search: str | None = None, user: str = Depends(_verify_token)):
    """Return trending topics, optionally filtered by a search query."""
    settings = Settings()
    agent = TrendAgent(settings)
    try:
        if search and search.strip():
            report = agent.search(search.strip())
        else:
            report = agent.fetch()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Trend fetch failed: {exc}")

    return [
        {
            "index": i,
            "title": t.title,
            "source": _source_label(t.source),
            "source_full": t.source,
            "score": t.score,
            "url": t.url or "",
        }
        for i, t in enumerate(report.trends, 1)
    ]


@app.post("/api/generate")
def generate_post(req: GenerateRequest, user: str = Depends(_verify_token)):
    """Fetch trends and generate social media content for the given slot."""
    settings = Settings()
    slot = _get_slot(req.slot)

    trend_agent = TrendAgent(settings)
    try:
        if req.search_query and req.search_query.strip():
            report = trend_agent.search(req.search_query.strip())
        else:
            report = trend_agent.fetch()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Trend fetch failed: {exc}")

    content_agent = ContentAgent(settings)
    try:
        post = content_agent.generate(
            trend_report=report,
            slot=slot,
            selected_topic=req.topic_title or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Content generation failed: {exc}")

    return {
        "topic": post.topic,
        "linkedin_content": post.linkedin_content,
        "hashtags": post.hashtags,
        "tag_string": post.tag_string,
        "linkedin_full": post.linkedin_full,
    }


@app.post("/api/publish")
def publish_post(req: PublishRequest, user: str = Depends(_verify_token)):
    """Publish a generated post to LinkedIn."""
    settings = Settings()

    if not settings.linkedin_enabled:
        raise HTTPException(status_code=503, detail="LinkedIn is not configured on this server.")

    # Resolve the author URN — prefer org page, fall back to personal profile
    if settings.linkedin_org_id:
        author_urn = f"urn:li:organization:{settings.linkedin_org_id}"
        label = "LinkedIn Org"
    else:
        author_urn = settings.linkedin_author_id
        label = "LinkedIn"

    # Build a GeneratedPost from the (possibly edited) frontend payload
    post = GeneratedPost(
        slot=PostSlot.TECHNICAL_DEEP_DIVE,  # placeholder; slot doesn't affect publishing
        topic=req.topic,
        twitter_content="",
        linkedin_content=req.linkedin_content,
        hashtags=req.hashtags,
    )

    platform = LinkedInPlatform(settings, author_urn=author_urn, label=label)
    try:
        ok = platform.post(post)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LinkedIn publish failed: {exc}")

    if not ok:
        raise HTTPException(status_code=502, detail="LinkedIn post returned failure.")

    return {"success": True, "post_id": "published"}


# ── Local dev fallback ─────────────────────────────────────────────────────────

@app.get("/")
def serve_index():
    html_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "public",
        "index.html",
    )
    if os.path.isfile(html_path):
        return FileResponse(html_path)
    return {"message": "Social Media Agent API is running. Visit /docs for the API reference."}

from __future__ import annotations

import requests
from dataclasses import dataclass, field
from typing import Optional

from src.config.settings import Settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Trend:
    title: str
    source: str
    url: Optional[str] = None
    score: float = 0.0
    description: str = ""


@dataclass
class TrendReport:
    trends: list[Trend] = field(default_factory=list)
    summary: str = ""

    def as_text(self) -> str:
        lines = [f"Top {len(self.trends)} trending topics:\n"]
        for i, t in enumerate(self.trends, 1):
            lines.append(f"{i}. [{t.source}] {t.title} (score: {t.score:.0f})")
            if t.url:
                lines.append(f"   URL: {t.url}")
        return "\n".join(lines)


class TrendAgent:
    """Aggregates trending tech topics from HackerNews, Reddit, Google Trends, and LinkedIn."""

    HN_TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
    HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._reddit = None
        self._init_reddit()

    # ── init helpers ──────────────────────────────────────────────────────────

    def _init_reddit(self) -> None:
        if not self.settings.reddit_enabled:
            return
        try:
            import praw  # noqa: PLC0415

            self._reddit = praw.Reddit(
                client_id=self.settings.reddit_client_id,
                client_secret=self.settings.reddit_client_secret,
                user_agent=self.settings.reddit_user_agent,
            )
            logger.info("Reddit client initialised")
        except Exception as exc:
            logger.warning(f"Reddit init failed: {exc}")

    # ── individual sources ────────────────────────────────────────────────────

    def _fetch_hackernews(self, count: int = 15) -> list[Trend]:
        try:
            ids = requests.get(self.HN_TOP_URL, timeout=10).json()[:count]
            trends: list[Trend] = []
            for story_id in ids:
                try:
                    item = requests.get(
                        self.HN_ITEM_URL.format(story_id), timeout=5
                    ).json()
                    if item and item.get("type") == "story":
                        trends.append(
                            Trend(
                                title=item.get("title", ""),
                                source="HackerNews",
                                url=item.get(
                                    "url",
                                    f"https://news.ycombinator.com/item?id={story_id}",
                                ),
                                score=float(item.get("score", 0)),
                            )
                        )
                except Exception:
                    pass
            logger.info(f"HackerNews: fetched {len(trends)} stories")
            return trends
        except Exception as exc:
            logger.error(f"HackerNews fetch failed: {exc}")
            return []

    def _fetch_reddit(self, count: int = 15) -> list[Trend]:
        if not self._reddit:
            return []
        subreddits = ["programming", "technology", "MachineLearning", "devops", "webdev",
                      "oracle", "oci", "cloudcomputing"]
        trends: list[Trend] = []
        per_sub = max(1, count // len(subreddits))
        try:
            for sub_name in subreddits:
                sub = self._reddit.subreddit(sub_name)
                for post in sub.hot(limit=per_sub):
                    if not post.stickied:
                        trends.append(
                            Trend(
                                title=post.title,
                                source=f"Reddit r/{sub_name}",
                                url=f"https://reddit.com{post.permalink}",
                                score=float(post.score),
                            )
                        )
            logger.info(f"Reddit: fetched {len(trends)} posts")
            return trends[:count]
        except Exception as exc:
            logger.error(f"Reddit fetch failed: {exc}")
            return []

    def _fetch_google_trends(self, count: int = 10) -> list[Trend]:
        """Fetch trending searches via the Google Trends daily RSS feed.

        More reliable than pytrends because it hits a stable public RSS endpoint
        rather than scraping the internal Google Trends API.
        """
        import xml.etree.ElementTree as ET

        RSS_URL = "https://trends.google.com/trending/rss?geo=US"
        NS = {"ht": "https://trends.google.com/trends/trendingsearches/daily"}

        try:
            resp = requests.get(
                RSS_URL,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SocialAgent/1.0)"},
            )
            resp.raise_for_status()

            root = ET.fromstring(resp.content)
            trends: list[Trend] = []

            for item in root.findall(".//item")[:count]:
                title_el = item.find("title")
                traffic_el = item.find("ht:approx_traffic", NS)
                news_url_el = item.find(".//ht:news_item_url", NS)

                if title_el is None or not title_el.text:
                    continue

                raw_traffic = (traffic_el.text or "0") if traffic_el is not None else "0"
                score = float(raw_traffic.replace(",", "").replace("+", "") or "0")

                trends.append(
                    Trend(
                        title=title_el.text.strip(),
                        source="Google Trends",
                        score=score,
                        url=news_url_el.text.strip() if news_url_el is not None else None,
                    )
                )

            logger.info(f"Google Trends: fetched {len(trends)} topics via RSS")
            return trends
        except Exception as exc:
            logger.error(f"Google Trends fetch failed: {exc}")
            return []

    def _fetch_linkedin(self, count: int = 15) -> list[Trend]:
        """Read trending posts from LinkedIn using the REST API (v202401).

        Iterates over a set of tech hashtags and pulls the most-liked recent posts
        from each one. Requires `linkedin_access_token` with at minimum the
        `r_liteprofile` and `w_member_social` scopes (the same token used for posting).
        """
        token = self.settings.linkedin_access_token
        if not token:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": "202401",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        # Tech hashtags to scan — ordered by expected signal strength
        tech_hashtags = [
            "artificialintelligence",
            "machinelearning",
            "softwareengineering",
            "devops",
            "cloudcomputing",
            "cybersecurity",
            "programming",
            "datascience",
            "oraclecloud",
            "oci",
            "oracledatabase",
            "oracleapex",
        ]

        trends: list[Trend] = []
        per_tag = max(2, count // len(tech_hashtags) + 1)

        for hashtag in tech_hashtags:
            try:
                resp = requests.get(
                    "https://api.linkedin.com/rest/posts",
                    params={
                        "q": "hashtag",
                        "hashtag": f"urn:li:hashtag:{hashtag}",
                        "count": per_tag,
                        "sortBy": "RELEVANCE",
                    },
                    headers=headers,
                    timeout=10,
                )
                if not resp.ok:
                    logger.debug(
                        f"LinkedIn #{hashtag}: HTTP {resp.status_code} – {resp.text[:120]}"
                    )
                    continue

                for post in resp.json().get("elements", []):
                    commentary: str = post.get("commentary", "")
                    if not commentary:
                        continue
                    # Use the first non-empty line as the trend title
                    first_line = next(
                        (ln.strip() for ln in commentary.splitlines() if ln.strip()), ""
                    )[:140]
                    if not first_line:
                        continue

                    # LinkedIn REST API embeds like/comment counts here
                    social = post.get("socialDetail", {})
                    counts = social.get("totalSocialActivityCounts", {})
                    score = float(
                        counts.get("numLikes", 0) + counts.get("numComments", 0) * 2
                    )

                    post_urn = post.get("id", "")
                    url = (
                        f"https://www.linkedin.com/feed/update/{post_urn}/"
                        if post_urn
                        else "https://www.linkedin.com/feed/"
                    )

                    trends.append(
                        Trend(
                            title=first_line,
                            source=f"LinkedIn #{hashtag}",
                            url=url,
                            score=score,
                        )
                    )
            except Exception as exc:
                logger.debug(f"LinkedIn #{hashtag} fetch error: {exc}")

        logger.info(f"LinkedIn: fetched {len(trends)} trending posts")
        return trends[:count]

    # ── public API ────────────────────────────────────────────────────────────

    def fetch(self) -> TrendReport:
        all_trends: list[Trend] = []
        all_trends.extend(self._fetch_hackernews(15))
        all_trends.extend(self._fetch_reddit(15))
        all_trends.extend(self._fetch_google_trends(10))
        all_trends.extend(self._fetch_linkedin(15))

        # Deduplicate by normalised title prefix
        seen: set[str] = set()
        unique: list[Trend] = []
        for t in all_trends:
            key = t.title[:60].lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)

        unique.sort(key=lambda t: t.score, reverse=True)
        report = TrendReport(trends=unique[:25])
        logger.info(f"TrendAgent aggregated {len(report.trends)} unique trends")
        return report

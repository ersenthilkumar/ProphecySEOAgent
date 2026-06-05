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

    # Keywords used to filter Google Trends results to tech-relevant topics only
    _TECH_KEYWORDS = {
        "ai", "ml", "llm", "gpt", "claude", "gemini", "openai", "anthropic",
        "software", "code", "coding", "developer", "programming", "algorithm",
        "cloud", "aws", "azure", "gcp", "oracle", "saas", "paas", "iaas",
        "api", "rest", "graphql", "microservice", "kubernetes", "docker", "devops",
        "python", "javascript", "typescript", "rust", "golang", "java", "kotlin",
        "database", "sql", "nosql", "postgres", "mongodb", "redis",
        "security", "cyber", "hack", "breach", "vulnerability", "ransomware", "cve",
        "tech", "startup", "github", "linux", "open source", "framework", "library",
        "gpu", "cpu", "chip", "nvidia", "semiconductor", "quantum",
        "robot", "automation", "data science", "machine learning", "deep learning",
        "neural", "model", "inference", "fine-tun", "rag", "vector",
        "web", "browser", "server", "network", "protocol", "encryption",
        "mobile", "ios", "android", "app store",
    }

    def _is_tech_trend(self, title: str) -> bool:
        lower = title.lower()
        return any(kw in lower for kw in self._TECH_KEYWORDS)

    def _fetch_google_trends(self, count: int = 10) -> list[Trend]:
        """Fetch trending searches via the Google Trends daily RSS feed, filtered to tech topics.

        The daily RSS covers all categories, so non-tech results (sports, celebrities) are
        dropped via keyword matching. Fetches a larger batch to improve the hit rate.
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

            # Scan more items than needed so filtering still yields enough results
            for item in root.findall(".//item")[:count * 5]:
                title_el = item.find("title")
                traffic_el = item.find("ht:approx_traffic", NS)
                news_url_el = item.find(".//ht:news_item_url", NS)

                if title_el is None or not title_el.text:
                    continue

                title = title_el.text.strip()
                if not self._is_tech_trend(title):
                    continue

                raw_traffic = (traffic_el.text or "0") if traffic_el is not None else "0"
                score = float(raw_traffic.replace(",", "").replace("+", "") or "0")

                trends.append(
                    Trend(
                        title=title,
                        source="Google Trends",
                        score=score,
                        url=news_url_el.text.strip() if news_url_el is not None else None,
                    )
                )
                if len(trends) >= count:
                    break

            logger.info(f"Google Trends: fetched {len(trends)} tech topics via RSS")
            return trends
        except Exception as exc:
            logger.error(f"Google Trends fetch failed: {exc}")
            return []

    def _fetch_devto(self, count: int = 15) -> list[Trend]:
        """Fetch trending developer articles from DEV.to public API.

        No API key required. Returns articles sorted by engagement over the past week,
        filtered to tech topics aligned with our focus area.
        """
        try:
            resp = requests.get(
                "https://dev.to/api/articles",
                params={"top": 7, "per_page": count * 2},
                headers={"User-Agent": "SocialMediaAgent/1.0"},
                timeout=10,
            )
            resp.raise_for_status()
            trends: list[Trend] = []
            for article in resp.json():
                title: str = article.get("title", "").strip()
                if not title or not self._is_tech_trend(title):
                    continue
                trends.append(
                    Trend(
                        title=title,
                        source="DEV.to",
                        url=article.get("url", ""),
                        score=float(
                            article.get("public_reactions_count", 0)
                            + article.get("comments_count", 0) * 2
                        ),
                        description=article.get("description", ""),
                    )
                )
                if len(trends) >= count:
                    break
            logger.info(f"DEV.to: fetched {len(trends)} trending articles")
            return trends
        except Exception as exc:
            logger.error(f"DEV.to fetch failed: {exc}")
            return []

    # ── search (topic-specific) ───────────────────────────────────────────────

    def _search_hackernews(self, query: str, count: int = 15) -> list[Trend]:
        """Search HackerNews stories via Algolia."""
        try:
            resp = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={"query": query, "tags": "story", "hitsPerPage": count},
                timeout=10,
            )
            resp.raise_for_status()
            trends: list[Trend] = []
            for hit in resp.json().get("hits", []):
                title = (hit.get("title") or "").strip()
                if not title:
                    continue
                trends.append(
                    Trend(
                        title=title,
                        source="HackerNews (search)",
                        url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                        score=float(hit.get("points") or 0),
                    )
                )
            logger.info(f"HackerNews search '{query}': {len(trends)} results")
            return trends
        except Exception as exc:
            logger.error(f"HackerNews search failed: {exc}")
            return []

    def _search_devto(self, query: str, count: int = 15) -> list[Trend]:
        """Search DEV.to articles by keyword."""
        try:
            resp = requests.get(
                "https://dev.to/api/articles",
                params={"q": query, "per_page": count, "top": 30},
                headers={"User-Agent": "SocialMediaAgent/1.0"},
                timeout=10,
            )
            resp.raise_for_status()
            trends: list[Trend] = []
            for article in resp.json():
                title = (article.get("title") or "").strip()
                if not title:
                    continue
                trends.append(
                    Trend(
                        title=title,
                        source="DEV.to (search)",
                        url=article.get("url", ""),
                        score=float(
                            article.get("public_reactions_count", 0)
                            + article.get("comments_count", 0) * 2
                        ),
                        description=article.get("description", ""),
                    )
                )
            logger.info(f"DEV.to search '{query}': {len(trends)} results")
            return trends
        except Exception as exc:
            logger.error(f"DEV.to search failed: {exc}")
            return []

    def _search_reddit(self, query: str, count: int = 15) -> list[Trend]:
        """Search Reddit across tech subreddits for the given query."""
        if not self._reddit:
            return []
        subreddits = "programming+technology+MachineLearning+devops+webdev+oracle+cloudcomputing"
        try:
            results = self._reddit.subreddit(subreddits).search(
                query, sort="relevance", time_filter="month", limit=count
            )
            trends: list[Trend] = []
            for post in results:
                if not post.stickied:
                    trends.append(
                        Trend(
                            title=post.title,
                            source="Reddit (search)",
                            url=f"https://reddit.com{post.permalink}",
                            score=float(post.score),
                        )
                    )
            logger.info(f"Reddit search '{query}': {len(trends)} results")
            return trends
        except Exception as exc:
            logger.error(f"Reddit search failed: {exc}")
            return []

    # ── public API ────────────────────────────────────────────────────────────

    def fetch(self) -> TrendReport:
        all_trends: list[Trend] = []
        all_trends.extend(self._fetch_hackernews(15))
        all_trends.extend(self._fetch_reddit(15))
        all_trends.extend(self._fetch_google_trends(10))
        all_trends.extend(self._fetch_devto(15))

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

    def search(self, query: str) -> TrendReport:
        """Search all available sources for articles related to `query`."""
        logger.info(f"Searching trends for: [bold]{query}[/bold]")
        all_trends: list[Trend] = []
        all_trends.extend(self._search_hackernews(query, 15))
        all_trends.extend(self._search_reddit(query, 15))
        all_trends.extend(self._search_devto(query, 15))

        seen: set[str] = set()
        unique: list[Trend] = []
        for t in all_trends:
            key = t.title[:60].lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)

        unique.sort(key=lambda t: t.score, reverse=True)
        report = TrendReport(trends=unique[:25])
        logger.info(f"Search returned {len(report.trends)} unique articles for '{query}'")
        return report

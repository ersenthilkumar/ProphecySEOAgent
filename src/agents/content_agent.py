from __future__ import annotations

import json
from enum import Enum
from dataclasses import dataclass, field

import anthropic

from src.agents.trend_agent import TrendReport
from src.config.settings import Settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PostSlot(str, Enum):
    MORNING_BRIEF = "morning_brief"        # 07:00 – quick trend snapshot
    TECHNICAL_DEEP_DIVE = "technical_deep_dive"  # 10:00 – code-heavy solution
    VISUAL_SHOWCASE = "visual_showcase"    # 15:00 – image-forward, punchy
    EVENING_BLOG = "evening_blog"          # 22:00 – long-form blog wrap-up


SLOT_INSTRUCTIONS: dict[PostSlot, str] = {
    PostSlot.MORNING_BRIEF: (
        "Create a SHORT morning brief post (energetic, 2-3 punchy sentences). "
        "Highlight the single most exciting tech trend of the day. "
        "End with a thought-provoking question to spark engagement."
    ),
    PostSlot.TECHNICAL_DEEP_DIVE: (
        "Create an IN-DEPTH technical solution post. Include a concrete code snippet "
        "(Python, JS, or Bash – pick the most relevant language), explain the WHY "
        "behind the approach, and link it to a current trending problem. "
        "LinkedIn content should be 800-1500 chars with clear sections."
    ),
    PostSlot.VISUAL_SHOWCASE: (
        "Create a VISUAL-FIRST post designed to accompany a striking infographic or "
        "diagram. The text should be concise (3-5 bullet points max) and reference "
        "what the image shows. Use bold section headers on LinkedIn."
    ),
    PostSlot.EVENING_BLOG: (
        "Create a COMPREHENSIVE evening summary. Write a full blog post in Markdown "
        "(1000-1500 words) that teaches readers a technical concept drawn from today's "
        "trends, including sections: Introduction, Core Concept, Step-by-Step Guide, "
        "Code Example, Best Practices, Conclusion. Also provide short Twitter/LinkedIn "
        "teaser posts that link to the blog."
    ),
}

GENERATE_POST_TOOL = {
    "name": "generate_social_post",
    "description": "Generate structured social media content for the given time slot.",
    "input_schema": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "The specific tech topic this post focuses on",
            },
            "twitter_content": {
                "type": "string",
                "description": "Post text for Twitter/X – max 270 chars (leave room for hashtags)",
            },
            "linkedin_content": {
                "type": "string",
                "description": "Post text for LinkedIn – can be up to 3000 chars with markdown",
            },
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "5-8 relevant hashtags (no # prefix)",
            },
            "image_prompt": {
                "type": "string",
                "description": (
                    "Detailed DALL-E 3 prompt for a visually stunning, professional "
                    "tech illustration. Specify style, colors, composition."
                ),
            },
            "blog_content": {
                "type": "string",
                "description": "Full Markdown blog post – only required for evening_blog slot",
            },
            "blog_title": {
                "type": "string",
                "description": "SEO-friendly blog post title",
            },
        },
        "required": [
            "topic",
            "twitter_content",
            "linkedin_content",
            "hashtags",
            "image_prompt",
        ],
    },
}


@dataclass
class GeneratedPost:
    slot: PostSlot
    topic: str
    twitter_content: str
    linkedin_content: str
    hashtags: list[str] = field(default_factory=list)
    image_prompt: str = ""
    blog_content: str = ""
    blog_title: str = ""
    image_path: str = ""

    @property
    def tag_string(self) -> str:
        return " ".join(f"#{h}" for h in self.hashtags)

    @property
    def twitter_full(self) -> str:
        text = self.twitter_content
        tags = self.tag_string
        combined = f"{text}\n\n{tags}"
        return combined[:280]

    @property
    def linkedin_full(self) -> str:
        return f"{self.linkedin_content}\n\n{self.tag_string}"


class ContentAgent:
    """Uses Claude to generate social posts tailored to each daily time slot."""

    SYSTEM_PROMPT = (
        "You are an expert technical content strategist and software engineer. "
        "Your audience is senior developers, CTOs, and tech enthusiasts. "
        "Every post must be technically accurate, engaging, and provide genuine value. "
        "Prioritise depth over buzzwords. Always ground content in real, practical use cases. "
        "Use clear, confident language — no filler phrases like 'In today's fast-paced world'."
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def generate(
        self,
        trend_report: TrendReport,
        slot: PostSlot,
        selected_topic: str | None = None,
    ) -> GeneratedPost:
        logger.info(f"Generating content for slot: {slot.value}")

        topic_instruction = (
            f"Focus specifically on this topic: {selected_topic}"
            if selected_topic
            else "Choose the single most compelling trend above and generate the post."
        )

        user_message = (
            f"Focus area: {self.settings.tech_focus}\n\n"
            f"{trend_report.as_text()}\n\n"
            f"Time slot instructions: {SLOT_INSTRUCTIONS[slot]}\n\n"
            f"{topic_instruction}"
        )

        response = self.client.messages.create(
            model=self.settings.claude_model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": self.SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # prompt caching
                }
            ],
            tools=[GENERATE_POST_TOOL],
            tool_choice={"type": "tool", "name": "generate_social_post"},
            messages=[{"role": "user", "content": user_message}],
        )

        # Extract tool use result
        tool_result = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if not tool_result:
            raise RuntimeError("Claude returned no tool_use block")

        data: dict = tool_result.input
        post = GeneratedPost(
            slot=slot,
            topic=data.get("topic", ""),
            twitter_content=data.get("twitter_content", ""),
            linkedin_content=data.get("linkedin_content", ""),
            hashtags=data.get("hashtags", []),
            image_prompt=data.get("image_prompt", ""),
            blog_content=data.get("blog_content", ""),
            blog_title=data.get("blog_title", ""),
        )
        logger.info(f"Generated post on topic: [bold]{post.topic}[/bold]")
        return post

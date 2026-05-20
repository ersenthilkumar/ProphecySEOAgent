#!/usr/bin/env python3
"""
One-shot .env cleaner.
- Strips non-key-value lines (profile text, box-drawing chars)
- Removes inline comments that break python-dotenv
- Deduplicates keys (last value in file wins)
- Rewrites a clean ASCII .env
"""
import re
from pathlib import Path

env_path = Path(".env")
raw = env_path.read_text(encoding="utf-8", errors="replace")

# ── Extract every KEY=VALUE line, last occurrence wins ────────────────────────
values: dict[str, str] = {}
for line in raw.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    m = re.match(r'^([A-Za-z][A-Za-z0-9_]*)=(.*)$', line)
    if not m:
        continue
    key = m.group(1)
    # Strip inline comment (everything from  ' #' onward)
    val = re.split(r'\s+#', m.group(2), maxsplit=1)[0].strip()
    values[key] = val

# ── Write clean file ──────────────────────────────────────────────────────────
SECTIONS = [
    ("Anthropic Claude (required)",  ["ANTHROPIC_API_KEY", "CLAUDE_MODEL"]),
    ("OpenAI DALL-E (required)",     ["OPENAI_API_KEY"]),
    ("Twitter/X (optional)",         ["TWITTER_API_KEY", "TWITTER_API_SECRET",
                                      "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_TOKEN_SECRET",
                                      "TWITTER_BEARER_TOKEN"]),
    ("LinkedIn",                     ["LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET",
                                      "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_AUTHOR_ID",
                                      "LINKEDIN_ORG_ID", "LINKEDIN_POST_AS",
                                      "LINKEDIN_REFRESH_TOKEN"]),
    ("Reddit (optional)",            ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
                                      "REDDIT_USER_AGENT"]),
    ("App settings",                 ["TIMEZONE", "TECH_FOCUS", "OUTPUT_DIR"]),
]

lines_out: list[str] = []
for section, keys in SECTIONS:
    lines_out.append(f"# --- {section} ---")
    for key in keys:
        lines_out.append(f"{key}={values.get(key, '')}")
    lines_out.append("")

env_path.write_text("\n".join(lines_out), encoding="utf-8")
print(".env cleaned successfully.\n")

# ── Report which required keys are still missing ──────────────────────────────
REQUIRED = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}
PLACEHOLDERS = {"sk-ant-your-key-here", "sk-your-openai-key-here", ""}

missing = [k for k in REQUIRED if values.get(k, "") in PLACEHOLDERS]
if missing:
    print("ACTION NEEDED - fill these in .env before running main.py:")
    for k in missing:
        print(f"  {k}=<your real key>")
else:
    print("All required keys are set.")

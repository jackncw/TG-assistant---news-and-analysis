"""Fetch news from configured RSS sources into categorised headline lists.

Output: data/latest/news.json
Run:    python scripts/fetch_news.py
"""
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.json"
OUT_PATH = ROOT / "data" / "latest" / "news.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TAG_RE = re.compile(r"<[^>]+>")


def clean_text(raw: str, max_chars: int) -> str:
    text = html.unescape(TAG_RE.sub(" ", raw or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def entry_published(entry) -> str:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return time.strftime("%Y-%m-%dT%H:%M:%SZ", t)
    return ""


def matches_keywords(title: str, keywords: list[str]) -> bool:
    for kw in keywords:
        if len(kw) <= 4:  # short keywords need word boundaries (avoid "AI" in "brain")
            if re.search(rf"\b{re.escape(kw)}\b", title, re.IGNORECASE):
                return True
        elif kw.lower() in title.lower():
            return True
    return False


def fetch_source(source: dict, params: dict) -> list[dict]:
    resp = requests.get(
        source["url"],
        headers={"User-Agent": params["user_agent"]},
        timeout=params["request_timeout"],
    )
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        raise ValueError("0 entries parsed")
    items = []
    for e in feed.entries:
        title = clean_text(e.get("title", ""), 200)
        if not title:
            continue
        if source.get("filter_keywords") and not matches_keywords(title, params["ai_filter_keywords"]):
            continue
        summary = clean_text(e.get("summary", e.get("description", "")), params["max_summary_chars"])
        if summary.startswith(title[:40]):  # many feeds repeat the title as summary
            summary = ""
        items.append(
            {
                "title": title,
                "summary": summary,
                "source": source["name"],
                "url": e.get("link", ""),
                "published": entry_published(e),
                "category": source["category"],
                "region": source["region"],
            }
        )
    return items


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    params = config["news_params"]
    sources = config["rss_sources"]

    categories: dict[str, list[dict]] = {}
    errors: list[str] = []
    ok_count = 0

    for source in sources:
        try:
            items = fetch_source(source, params)
            categories.setdefault(source["category"], []).extend(items)
            ok_count += 1
            print(f"OK   {source['name']}: {len(items)} items")
        except Exception as ex:
            errors.append(f"{source['name']}: {type(ex).__name__}: {ex}")
            print(f"SKIP {source['name']}: {type(ex).__name__}: {str(ex)[:80]}")

    if ok_count == 0:
        print("ERROR: all sources failed", file=sys.stderr)
        return 1

    max_items = params["max_items_per_category"]
    seen_titles: set[str] = set()
    for cat, items in categories.items():
        items.sort(key=lambda x: x["published"], reverse=True)
        deduped = []
        for item in items:
            key = item["title"][:60]
            if key in seen_titles:
                continue
            seen_titles.add(key)
            deduped.append(item)
        categories[cat] = deduped[:max_items]

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "categories": categories,
        "errors": errors,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {c: len(v) for c, v in categories.items()}
    print(f"OK: {ok_count}/{len(sources)} sources, counts={counts} -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

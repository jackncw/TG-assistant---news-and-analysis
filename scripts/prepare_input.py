"""Merge market.json + news.json into a compact claude_input.json (<8k tokens).

Output: data/latest/claude_input.json
Run:    python scripts/prepare_input.py [--run-type morning|hk-close|evening|manual]
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LATEST = ROOT / "data" / "latest"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MAX_NEWS_PER_CATEGORY = 20
MAX_SUMMARY_CHARS = 80

STOCK_COLUMNS = [
    "ticker", "name", "close", "change_pct", "rsi14", "momentum_20d_pct",
    "vol_ratio", "above_ma50", "above_ma200", "pct_from_52w_high",
]


def estimate_tokens(text: str) -> int:
    """Rough estimate: CJK chars ~1 token each, other chars ~4 per token."""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return cjk + (len(text) - cjk) // 4


def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def index_summary(block: dict | None) -> dict | None:
    if not block:
        return None
    return {k: v for k, v in block.items() if k != "history_30d"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-type", default="manual",
                        choices=["morning", "hk-close", "evening", "manual"])
    args = parser.parse_args()

    market = load_json(LATEST / "market.json")
    news = load_json(LATEST / "news.json")
    if market is None or news is None:
        print("ERROR: run fetch_market.py and fetch_news.py first", file=sys.stderr)
        return 1

    news_out = {}
    for cat, items in news.get("categories", {}).items():
        news_out[cat] = [
            {
                "t": item["title"],
                "s": item["summary"][:MAX_SUMMARY_CHARS],
                "src": item["source"],
            }
            for item in items[:MAX_NEWS_PER_CATEGORY]
        ]

    prev_report = load_json(LATEST / "report.json")
    prev_summary = None
    if prev_report:
        prev_summary = {
            "generated_at": prev_report.get("generated_at", ""),
            "one_line_digest": prev_report.get("one_line_digest", ""),
            "hsi_outlook": prev_report.get("market", {}).get("hsi_outlook", ""),
        }

    out = {
        "run_type": args.run_type,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "market": {
            "hsi": index_summary(market.get("hsi")),
            "hscei": index_summary(market.get("hscei")),
            "stock_columns": STOCK_COLUMNS,
            "stocks": [[s.get(c) for c in STOCK_COLUMNS] for s in market.get("stocks", [])],
        },
        "news": news_out,
        "prev_report": prev_summary,
    }

    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    out_path = LATEST / "claude_input.json"
    out_path.write_text(text, encoding="utf-8")

    tokens = estimate_tokens(text)
    counts = {c: len(v) for c, v in news_out.items()}
    print(f"OK: {len(text)} chars, ~{tokens} tokens (target <8000), news={counts} -> {out_path}")
    if tokens >= 8000:
        print("WARNING: estimated tokens >= 8000, consider trimming", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

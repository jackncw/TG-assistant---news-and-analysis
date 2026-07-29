"""Assemble compact Q&A context: last 3 days of reports + latest market data.

Output: data/latest/answer_context.json
Run:    python scripts/prepare_answer_context.py --question "..."
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HKT = timezone(timedelta(hours=8))
LATEST = ROOT / "data" / "latest"
ARCHIVE = ROOT / "data" / "archive"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

MAX_ARCHIVE_DAYS = 3
STOCK_COLUMNS = [
    "ticker", "name", "close", "change_pct", "rsi14", "momentum_20d_pct",
    "vol_ratio", "above_ma50", "above_ma200", "pct_from_52w_high",
]


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def index_summary(block):
    if not block:
        return None
    return {k: v for k, v in block.items() if k != "history_30d"}


def hkt_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(HKT).date().isoformat()
    except ValueError:
        return ""


def market_as_of(market: dict) -> str:
    """Actual trading date of the close data (fetch timestamp can be next day HKT)."""
    for idx in ("hsi", "hscei"):
        hist = (market.get(idx) or {}).get("history_30d") or []
        if hist and hist[-1].get("date"):
            return hist[-1]["date"]
    return hkt_date(market.get("generated_at", ""))


def recent_reports() -> list[dict]:
    """Latest report plus reports from the newest archive days (deduped by
    generated_at), newest first, capped at MAX_ARCHIVE_DAYS days of archive."""
    reports = []
    seen = set()

    def add(report):
        if not report:
            return
        key = report.get("generated_at", "")
        if key in seen:
            return
        seen.add(key)
        reports.append({
            "generated_at": key,
            "report_date_hkt": hkt_date(key),
            "run_type": report.get("run_type", ""),
            "one_line_digest": report.get("one_line_digest", ""),
            "hsi_analysis": report.get("market", {}).get("hsi_analysis", ""),
            "hsi_outlook": report.get("market", {}).get("hsi_outlook", ""),
            "top_picks": [
                {"ticker": p.get("ticker"), "name": p.get("name")}
                for p in report.get("market", {}).get("top_picks", [])
            ],
            "news_summaries": {
                cat: report.get(cat, {}).get("summary", "")
                for cat in ("news_hk", "news_uk", "news_world", "ai")
            },
            "trending": report.get("trending", {}),
        })

    add(load_json(LATEST / "report.json"))
    if ARCHIVE.exists():
        day_dirs = sorted((d for d in ARCHIVE.iterdir() if d.is_dir()), reverse=True)
        for day_dir in day_dirs[:MAX_ARCHIVE_DAYS]:
            for run_dir in sorted(day_dir.iterdir(), reverse=True):
                add(load_json(run_dir / "report.json"))
    return reports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    args = parser.parse_args()

    question = args.question.strip()[:500]
    if not question:
        print("ERROR: empty question", file=sys.stderr)
        return 1

    market = load_json(LATEST / "market.json")
    reports = recent_reports()
    if market is None and not reports:
        print("ERROR: no market data and no reports available", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    out = {
        "question": question,
        "prepared_at": now.isoformat(timespec="seconds"),
        "today_hkt": now.astimezone(HKT).date().isoformat(),
        "market": None,
        "recent_reports": reports,
    }
    if market:
        out["market"] = {
            "as_of_date": market_as_of(market),
            "generated_at": market.get("generated_at", ""),
            "hsi": index_summary(market.get("hsi")),
            "hscei": index_summary(market.get("hscei")),
            "stock_columns": STOCK_COLUMNS,
            "stocks": [[s.get(c) for c in STOCK_COLUMNS] for s in market.get("stocks", [])],
        }

    text = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    out_path = LATEST / "answer_context.json"
    out_path.write_text(text, encoding="utf-8")
    print(f"OK: {len(text)} chars, {len(reports)} report(s) -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

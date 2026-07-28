"""Send Telegram notifications for briefing runs.

Usage:
  python scripts/notify.py briefing              # send success briefing from data/latest
  python scripts/notify.py failure --step NAME   # send failure notification

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (required to send)
     GITHUB_REPOSITORY (owner/repo, for dashboard link), GITHUB_RUN_URL (failure link)
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LATEST = ROOT / "data" / "latest"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TG_LIMIT = 3900  # Telegram hard limit is 4096; leave headroom
HKT = timezone(timedelta(hours=8))

RUN_TYPE_LABEL = {"morning": "早晨", "hk-close": "港股收市", "evening": "晚間", "manual": "手動"}


def sanitize_md(text) -> str:
    """Strip characters that break Telegram legacy-Markdown entity parsing
    from dynamic (model/RSS-derived) text. Static formatting is added after."""
    return re.sub(r"[*_`\[\]]", "", str(text or ""))


def clip(text, max_chars: int = 150) -> str:
    text = sanitize_md(text).strip()
    return text[: max_chars - 1] + "…" if len(text) > max_chars else text


def first_sentence(text, max_chars: int = 150) -> str:
    text = sanitize_md(text).strip()
    for mark in ("。", ";", ";"):
        pos = text.find(mark)
        if pos > 0:
            return text[: pos + 1]
    return clip(text, max_chars)


def hkt_label(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(HKT)
        return dt.strftime("%d/%m %H:%M")
    except ValueError:
        return ""


def build_briefing_message(report: dict, market: dict, dashboard_url: str) -> str:
    run_label = RUN_TYPE_LABEL.get(report.get("run_type", ""), report.get("run_type", ""))
    when = hkt_label(report.get("generated_at", ""))
    mkt = report.get("market", {})
    hsi = (market or {}).get("hsi") or {}

    lines = [f"📊 *每日簡報* · {run_label} · {when} HKT", "", clip(report.get("one_line_digest"), 120)]

    if hsi.get("close") is not None:
        chg = hsi.get("change_pct")
        sign = "+" if (chg or 0) >= 0 else ""
        lines += ["", "*港股*", f"恆指 {hsi['close']:,.2f}({sign}{chg}%),RSI {hsi.get('rsi14', '–')}"]
    else:
        lines += ["", "*港股*"]
    picks = mkt.get("top_picks") or []
    if picks:
        lines.append("精選:" + "、".join(sanitize_md(p.get("name") or p.get("ticker")) for p in picks[:5]))
    if mkt.get("hsi_outlook"):
        lines.append(first_sentence(mkt["hsi_outlook"]))

    for title, block in (("香港", report.get("news_hk")), ("英國", report.get("news_uk")),
                         ("世界", report.get("news_world")), ("AI", report.get("ai"))):
        if block and block.get("summary"):
            lines += ["", f"*{title}*", clip(block["summary"], 200)]

    trending = report.get("trending") or {}
    trend_bits = [f"{name} {clip(trending[key], 60)}"
                  for name, key in (("港:", "hk"), ("英:", "uk"), ("全球:", "global")) if trending.get(key)]
    if trend_bits:
        lines += ["", "*熱門*"] + trend_bits

    lines += [""]
    if dashboard_url:
        lines.append(f"📈 {dashboard_url}")
    lines.append("_以上分析僅供參考,並非投資建議。投資涉及風險,買賣決定請自行判斷。_")
    return "\n".join(lines)


def build_failure_message(step: str, run_url: str) -> str:
    lines = ["⚠️ *briefing run 失敗*", f"死喺:{sanitize_md(step) or '未知 step'}"]
    if run_url:
        lines.append(run_url)
    lines.append("data/latest 未有覆寫,舊數據保留。")
    return "\n".join(lines)


def split_message(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Split into <=limit chunks, preferring line boundaries."""
    if len(text) <= limit:
        return [text]
    parts = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 1, limit + 1)
        if cut <= 0:
            cut = limit
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        parts.append(remaining)
    return parts


def send_message(token: str, chat_id: str, text: str) -> None:
    """Send one message; falls back to plain text if Markdown parsing fails."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown",
               "disable_web_page_preview": True}
    resp = requests.post(url, json=payload, timeout=20)
    if resp.status_code == 400:  # bad entities -> retry unformatted so it still arrives
        payload.pop("parse_mode")
        resp = requests.post(url, json=payload, timeout=20)
    resp.raise_for_status()


def dashboard_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["briefing", "failure"])
    parser.add_argument("--step", default="", help="failed step name (failure mode)")
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return 1

    if args.mode == "briefing":
        report = json.loads((LATEST / "report.json").read_text(encoding="utf-8"))
        try:
            market = json.loads((LATEST / "market.json").read_text(encoding="utf-8"))
        except Exception:
            market = {}
        text = build_briefing_message(report, market, dashboard_url())
    else:
        text = build_failure_message(args.step, os.environ.get("GITHUB_RUN_URL", ""))

    parts = split_message(text)
    for i, part in enumerate(parts):
        try:
            send_message(token, chat_id, part)
        except Exception as ex:
            print(f"ERROR: send part {i + 1}/{len(parts)} failed: {ex}", file=sys.stderr)
            return 1
    print(f"OK: sent {len(parts)} message(s), {len(text)} chars total")
    return 0


if __name__ == "__main__":
    sys.exit(main())

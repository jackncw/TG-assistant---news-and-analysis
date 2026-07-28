"""Send Telegram notifications for briefing runs.

Usage:
  python scripts/notify.py briefing              # send success briefing from data/latest
  python scripts/notify.py failure --step NAME   # send failure notification

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (required to send)
     GITHUB_REPOSITORY (owner/repo, for dashboard link), GITHUB_RUN_URL (failure link)
"""
import argparse
import html
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

DISCLAIMER = "以上分析僅供參考,並非投資建議。投資涉及風險,買賣決定請自行判斷。"

SENTENCE_ENDS = "。;;!?"


def esc_html(text) -> str:
    """Escape dynamic (model/RSS-derived) text for Telegram HTML parse mode."""
    return html.escape(str(text or ""), quote=False)


def strip_tags(text: str) -> str:
    """Remove HTML tags for the plain-text fallback send."""
    return re.sub(r"<[^>]+>", "", text)


def sentence_clip(text, max_chars: int = 200) -> str:
    """Fit text into max_chars by cutting ONLY at a sentence end; a hard cut
    with ellipsis is the last resort when no sentence end exists in range."""
    text = str(text or "").strip()
    if len(text) <= max_chars:
        return text
    best = -1
    for mark in SENTENCE_ENDS:
        pos = text.rfind(mark, 0, max_chars)
        best = max(best, pos)
    if best > 0:
        return text[: best + 1]
    return text[: max_chars - 1] + "…"


def first_sentence(text, max_chars: int = 150) -> str:
    text = str(text or "").strip()
    for mark in SENTENCE_ENDS:
        pos = text.find(mark)
        if 0 < pos < max_chars:
            return text[: pos + 1]
    return sentence_clip(text, max_chars)


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

    lines = [f"📊 <b>每日簡報</b> · {esc_html(run_label)} · {when} HKT", "",
             esc_html(sentence_clip(report.get("one_line_digest"), 120))]

    lines += ["", "<b>港股</b>"]
    if hsi.get("close") is not None:
        chg = hsi.get("change_pct")
        sign = "+" if (chg or 0) >= 0 else ""
        lines.append(f"恆指 {hsi['close']:,.2f}({sign}{chg}%),RSI {hsi.get('rsi14', '–')}")
    picks = mkt.get("top_picks") or []
    if picks:
        lines.append("精選:" + "、".join(esc_html(p.get("name") or p.get("ticker")) for p in picks[:5]))
    if mkt.get("hsi_outlook"):
        lines.append(esc_html(first_sentence(mkt["hsi_outlook"])))

    for title, block in (("香港", report.get("news_hk")), ("英國", report.get("news_uk")),
                         ("世界", report.get("news_world")), ("AI", report.get("ai"))):
        if block and block.get("summary"):
            lines += ["", f"<b>{title}</b>", esc_html(sentence_clip(block["summary"], 200))]

    trending = report.get("trending") or {}
    trend_bits = [f"{name} {esc_html(sentence_clip(trending[key], 120))}"
                  for name, key in (("港:", "hk"), ("英:", "uk"), ("全球:", "global")) if trending.get(key)]
    if trend_bits:
        lines += ["", "<b>熱門</b>"] + trend_bits

    if dashboard_url:
        lines += ["", f'📈 <a href="{dashboard_url}">開 dashboard</a>']
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


def build_failure_message(step: str, run_url: str) -> str:
    lines = ["⚠️ <b>briefing run 失敗</b>", f"死喺:{esc_html(step) or '未知 step'}"]
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
    """Send one message; falls back to tag-stripped plain text if HTML parsing fails."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    resp = requests.post(url, json=payload, timeout=20)
    if resp.status_code == 400:  # bad entities -> resend unformatted so it still arrives
        payload.pop("parse_mode")
        payload["text"] = strip_tags(text)
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

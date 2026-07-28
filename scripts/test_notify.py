"""Unit checks for message building in notify.py (no network).

Run: python scripts/test_notify.py  (exit 0 = all pass)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notify import (  # noqa: E402
    TG_LIMIT,
    build_briefing_message,
    build_failure_message,
    esc_html,
    sentence_clip,
    split_message,
    strip_tags,
)

failures = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {name}" + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


SAMPLE_REPORT = {
    "generated_at": "2026-07-28T22:00:14+00:00",
    "run_type": "hk-close",
    "one_line_digest": "港股穩守50日線,熊本地震成焦點。",
    "news_hk": {"summary": "香港新聞總結兩三句。", "items": []},
    "news_uk": {"summary": "英國新聞總結。", "items": []},
    "news_world": {"summary": "世界新聞總結。", "items": []},
    "ai": {"summary": "AI 動態總結。", "items": []},
    "trending": {"hk": "香港熱話一句。", "uk": "英國熱話一句。", "global": "全球熱話一句。"},
    "market": {
        "hsi_analysis": "恆指分析…",
        "hsi_outlook": "短期展望第一句。第二句唔應該出現晒。",
        "top_picks": [
            {"ticker": "9618.HK", "name": "京東集團"},
            {"ticker": "0939.HK", "name": "建設銀行"},
        ],
    },
}
SAMPLE_MARKET = {"hsi": {"close": 25310.85, "change_pct": 0.41, "rsi14": 60.8}}
DASH = "https://example.github.io/repo/"

# --- HTML formatting ---
msg = build_briefing_message(SAMPLE_REPORT, SAMPLE_MARKET, DASH)
check("digest included", "港股穩守50日線" in msg)
check("hsi close included", "25,310.85" in msg and "+0.41%" in msg)
check("picks included", "京東集團" in msg and "建設銀行" in msg)
check("section headers use <b>", "<b>香港</b>" in msg and "<b>港股</b>" in msg)
check("no markdown asterisk headers", "*香港*" not in msg)
check("dashboard link is <a href>", f'<a href="{DASH}">' in msg)
check("run type labelled", "港股收市" in msg)
check("HK time shown", "06:00" in msg)  # 22:00 UTC = 06:00 HKT next day

# disclaimer: plain text on its own line, blank line before it
lines = msg.split("\n")
disc_idx = [i for i, l in enumerate(lines) if l.startswith("以上分析僅供參考")]
check("disclaimer is a standalone plain line", bool(disc_idx))
if disc_idx:
    i = disc_idx[0]
    check("disclaimer has no HTML tags", "<" not in lines[i])
    check("blank line before disclaimer", i > 0 and lines[i - 1] == "")
    check("link line is above the blank line", i > 1 and DASH in lines[i - 2])

# --- dynamic text: HTML-escaped, markdown chars preserved ---
check("esc_html escapes angle brackets", esc_html("a<b>&c") == "a&lt;b&gt;&amp;c")
dirty = dict(SAMPLE_REPORT)
dirty["one_line_digest"] = "壞字元 <script> & *加粗* _斜體_"
msg2 = build_briefing_message(dirty, SAMPLE_MARKET, DASH)
check("html chars escaped in message", "&lt;script&gt;" in msg2 and "<script>" not in msg2)
check("markdown chars kept as literal text", "*加粗*" in msg2 and "_斜體_" in msg2)

# --- sentence_clip: only cuts at sentence end ---
check("short text unchanged", sentence_clip("一句完整。", 60) == "一句完整。")
two = "第一句有內容。第二句好長" + "字" * 60 + "。"
clipped = sentence_clip(two, 20)
check("clip cuts at full stop", clipped == "第一句有內容。", f"got={clipped!r}")
no_stop = "冇句號嘅超長文字" * 20
clipped2 = sentence_clip(no_stop, 30)
check("no full stop falls back to hard cut", clipped2.endswith("…") and len(clipped2) <= 30)

# trending long paragraph gets sentence-boundary cut in the real message
dirty2 = dict(SAMPLE_REPORT)
dirty2["trending"] = {"hk": "頭一句講體育賽事。跟住嘅第二句非常長," + "細" * 100 + "。", "uk": "", "global": ""}
msg3 = build_briefing_message(dirty2, SAMPLE_MARKET, DASH)
check("trending clipped at sentence end", "頭一句講體育賽事。" in msg3 and "細細" not in msg3)

# --- splitting (unchanged behaviour) ---
check("short message single part", split_message("abc") == ["abc"])
long_text = "\n".join(f"第{i}行:" + "字" * 80 for i in range(200))
parts = split_message(long_text)
check("long message split", len(parts) > 1)
check("all parts within limit", all(len(p) <= TG_LIMIT for p in parts))
check("no content lost", "".join(parts).replace("\n", "") == long_text.replace("\n", ""))

# --- strip_tags for the plain-text fallback ---
check("strip_tags removes tags keeps text",
      strip_tags('前 <b>粗</b> <a href="http://x/">連結</a> 後') == "前 粗 連結 後")

# --- failure message ---
fmsg = build_failure_message("Generate report (claude -p)", "https://github.com/x/y/actions/runs/1")
check("failure names step", "Generate report" in fmsg)
check("failure has run link", "actions/runs/1" in fmsg)
check("failure clearly flagged", "失敗" in fmsg)
check("failure uses <b> header", "<b>" in fmsg)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("ALL PASS")
sys.exit(0)

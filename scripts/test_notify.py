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
    sanitize_md,
    split_message,
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
    "trending": {"hk": "香港熱話一段。", "uk": "英國熱話一段。", "global": "全球熱話一段。"},
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

# --- briefing message content ---
msg = build_briefing_message(SAMPLE_REPORT, SAMPLE_MARKET, DASH)
check("digest included", "港股穩守50日線" in msg)
check("hsi close included", "25,310.85" in msg and "+0.41%" in msg)
check("picks included", "京東集團" in msg and "建設銀行" in msg)
check("hk summary included", "香港新聞總結兩三句。" in msg)
check("uk summary included", "英國新聞總結。" in msg)
check("world summary included", "世界新聞總結。" in msg)
check("ai summary included", "AI 動態總結。" in msg)
check("dashboard link included", DASH in msg)
check("disclaimer included", "僅供參考" in msg)
check("run type labelled", "港股收市" in msg)
check("HK time shown", "06:00" in msg)  # 22:00 UTC = 06:00 HKT next day

# --- markdown sanitising of dynamic text ---
check("sanitize strips markdown chars", sanitize_md("a*b_c`d[e]f") == "abcdef")
dirty = dict(SAMPLE_REPORT)
dirty["one_line_digest"] = "壞字元 *加粗* _斜體_ [link] `code`"
msg2 = build_briefing_message(dirty, SAMPLE_MARKET, DASH)
check("dynamic text sanitised in message", "*加粗*" not in msg2 and "加粗" in msg2)

# --- splitting ---
check("short message single part", split_message("abc") == ["abc"])
long_text = "\n".join(f"第{i}行:" + "字" * 80 for i in range(200))
parts = split_message(long_text)
check("long message split", len(parts) > 1)
check("all parts within limit", all(len(p) <= TG_LIMIT for p in parts))
check("no content lost", "".join(parts).replace("\n", "") == long_text.replace("\n", ""))
check("split at line boundaries", all(not p.startswith("字") for p in parts[1:]))

# --- failure message ---
fmsg = build_failure_message("Generate report (claude -p)", "https://github.com/x/y/actions/runs/1")
check("failure names step", "Generate report" in fmsg)
check("failure has run link", "actions/runs/1" in fmsg)
check("failure clearly flagged", "失敗" in fmsg)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("ALL PASS")
sys.exit(0)

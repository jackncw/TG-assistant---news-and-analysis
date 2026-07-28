"""Unit checks for the close-repair logic in fetch_market.py.

Run: python scripts/test_fetch_market.py  (exit 0 = all pass)

Covers the rule set:
- a missing completed (past) trading day is always patched from intraday
- "today" is only patched when HK time >= 16:10 (post closing auction)
- an existing daily row is never overwritten
- NaN intraday prices are skipped
"""
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_market import patch_missing_closes  # noqa: E402

HK = ZoneInfo("Asia/Hong_Kong")

failures = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"{status}: {name}" + (f" ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def series(days_prices: dict[date, float]) -> pd.Series:
    return pd.Series({pd.Timestamp(d): p for d, p in days_prices.items()}).sort_index()


D22, D23, D24, D25 = date(2026, 7, 22), date(2026, 7, 23), date(2026, 7, 24), date(2026, 7, 25)

# --- past gap is patched regardless of time of day ---
close = series({D22: 100.0, D24: 102.0})
patched, added = patch_missing_closes(
    close.copy(), {D23: 101.0}, datetime(2026, 7, 25, 9, 0, tzinfo=HK))
check("past missing day patched", added == [str(D23)], f"added={added}")
check("past patch value correct",
      float(patched.loc[pd.Timestamp(D23)]) == 101.0)

# --- today before 16:10 HK: not patched ---
close = series({D23: 101.0, D24: 102.0})
patched, added = patch_missing_closes(
    close.copy(), {D25: 103.0}, datetime(2026, 7, 25, 16, 9, tzinfo=HK))
check("today NOT patched at 16:09", added == [], f"added={added}")

# --- today at exactly 16:10 HK: patched ---
patched, added = patch_missing_closes(
    close.copy(), {D25: 103.0}, datetime(2026, 7, 25, 16, 10, tzinfo=HK))
check("today patched at 16:10", added == [str(D25)], f"added={added}")
check("today patch value correct",
      added and float(patched.loc[pd.Timestamp(D25)]) == 103.0)

# --- today well after close (hk-close run, 16:30): patched ---
patched, added = patch_missing_closes(
    close.copy(), {D25: 103.5}, datetime(2026, 7, 25, 16, 30, tzinfo=HK))
check("today patched at 16:30", added == [str(D25)], f"added={added}")

# --- existing daily row never overwritten, even after 16:10 ---
close = series({D24: 102.0, D25: 999.0})
patched, added = patch_missing_closes(
    close.copy(), {D25: 103.0}, datetime(2026, 7, 25, 17, 0, tzinfo=HK))
check("existing row not overwritten", added == [], f"added={added}")
check("existing value untouched", float(patched.loc[pd.Timestamp(D25)]) == 999.0)

# --- NaN intraday price skipped ---
close = series({D22: 100.0, D24: 102.0})
patched, added = patch_missing_closes(
    close.copy(), {D23: float("nan")}, datetime(2026, 7, 25, 9, 0, tzinfo=HK))
check("NaN intraday skipped", added == [], f"added={added}")

# --- result stays date-sorted after patching a middle gap ---
close = series({D22: 100.0, D24: 102.0})
patched, _ = patch_missing_closes(
    close.copy(), {D23: 101.0}, datetime(2026, 7, 25, 9, 0, tzinfo=HK))
check("series sorted after patch", list(patched.index) == sorted(patched.index))

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("ALL PASS")
sys.exit(0)

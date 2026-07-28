"""Fetch HK market data via yfinance and compute technical indicators.

Output: data/latest/market.json
Run:    python scripts/fetch_market.py
"""
import json
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.json"
OUT_PATH = ROOT / "data" / "latest" / "market.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def clean_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows with a real close (drops intraday partial rows),
    sorted and deduped by date (Yahoo occasionally returns bad rows)."""
    df = df[df["Close"].notna()].sort_index()
    return df[~df.index.duplicated(keep="last")]


# HKEX closing auction ends ~16:08-16:10 HK time; after this the last
# intraday bar of the day is the settled closing price.
HK_CLOSE_CUTOFF = time(16, 10)


def patch_missing_closes(close: pd.Series, daily_last, now_hk: datetime) -> tuple[pd.Series, list[str]]:
    """Patch days missing from the daily close series using the last intraday
    price per day (daily_last: mapping of date -> price). Days strictly before
    today (HK time) are always patchable; today itself only once HK time has
    reached HK_CLOSE_CUTOFF, so a mid-session price is never mistaken for a
    daily close. Existing rows are never overwritten."""
    today_hk = now_hk.date()
    today_settled = now_hk.time() >= HK_CLOSE_CUTOFF
    have = {ts.date() for ts in close.index}
    added = []
    for day, px in daily_last.items():
        if day in have or pd.isna(px):
            continue
        if day < today_hk or (day == today_hk and today_settled):
            close.loc[pd.Timestamp(day)] = float(px)
            added.append(str(day))
    return (close.sort_index(), added) if added else (close, [])


def repair_recent_gaps(ticker: str, close: pd.Series) -> tuple[pd.Series, list[str]]:
    """Yahoo's daily series sometimes drops a recent trading day entirely
    (seen on ^HSI). Patch missing days from 60m intraday bars via
    patch_missing_closes (today included only after the close settles)."""
    try:
        intra = yf.Ticker(ticker).history(period="7d", interval="60m", auto_adjust=False)
    except Exception:
        return close, []
    if intra.empty:
        return close, []
    daily_last = intra["Close"].groupby(intra.index.date).last()
    return patch_missing_closes(close, daily_last, datetime.now(ZoneInfo("Asia/Hong_Kong")))


def rsi14(close: pd.Series) -> float | None:
    """Wilder's RSI over 14 periods; None if not enough data."""
    if len(close) < 15:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14).mean()
    last_loss = loss.iloc[-1]
    if pd.isna(last_loss):
        return None
    if last_loss == 0:
        return 100.0
    rs = gain.iloc[-1] / last_loss
    return round(100 - 100 / (1 + rs), 1)


def sma(close: pd.Series, n: int) -> float | None:
    if len(close) < n:
        return None
    return round(float(close.tail(n).mean()), 2)


def pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 2)


def index_block(close: pd.Series, history_output_days: int) -> dict:
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    hist = [
        {"date": d.strftime("%Y-%m-%d"), "close": round(float(v), 2)}
        for d, v in close.tail(history_output_days).items()
    ]
    return {
        "close": round(last, 2),
        "change_pct": pct(last, prev),
        "ma20": sma(close, 20),
        "ma50": sma(close, 50),
        "ma200": sma(close, 200),
        "rsi14": rsi14(close),
        "history_30d": hist,
    }


def stock_block(df: pd.DataFrame, ticker: str, name: str) -> dict | None:
    """df: per-ticker OHLCV frame already passed through clean_daily,
    so Close and Volume stay row-aligned. Returns None if unusable."""
    close = df["Close"]
    vol = df["Volume"]
    if len(close) < 21:
        return None
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    ma50 = sma(close, 50)
    ma200 = sma(close, 200)
    high_52w = float(close.tail(250).max())
    vol_ratio = None
    avg_vol = float(vol.tail(21).head(20).mean())
    if len(vol) >= 21 and avg_vol > 0 and not pd.isna(vol.iloc[-1]):
        vol_ratio = round(float(vol.iloc[-1]) / avg_vol, 2)
    return {
        "ticker": ticker,
        "name": name,
        "close": round(last, 2),
        "change_pct": pct(last, prev),
        "rsi14": rsi14(close),
        "momentum_20d_pct": pct(last, float(close.iloc[-21])),
        "vol_ratio": vol_ratio,
        "above_ma50": bool(last > ma50) if ma50 else None,
        "above_ma200": bool(last > ma200) if ma200 else None,
        "pct_from_52w_high": pct(last, high_52w),
    }


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    mkt = config["market"]
    period_days = int(mkt["history_days"] * 1.6)  # calendar days to cover trading days

    indices_cfg = mkt["indices"]
    stocks_cfg = mkt["stocks"]
    tickers = [i["ticker"] for i in indices_cfg] + [s["ticker"] for s in stocks_cfg]

    print(f"Downloading {len(tickers)} tickers...")
    data = yf.download(
        tickers,
        period=f"{period_days}d",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        threads=True,
        progress=False,
    )
    if data is None or data.empty:
        print("ERROR: yfinance returned no data at all", file=sys.stderr)
        return 1

    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    errors: list[str] = []

    for idx in indices_cfg:
        key = "hsi" if idx["ticker"] == "^HSI" else "hscei"
        try:
            close = clean_daily(data[idx["ticker"]])["Close"]
            close, added = repair_recent_gaps(idx["ticker"], close)
            if added:
                print(f"{idx['ticker']}: patched missing daily rows from intraday: {added}")
            if len(close) < 2:
                raise ValueError("insufficient rows")
            out[key] = index_block(close, mkt["history_output_days"])
            tail = ", ".join(f"{d.strftime('%Y-%m-%d')}={v:.2f}" for d, v in close.tail(5).items())
            print(f"{idx['ticker']} last 5 closes used for MA: {tail}")
        except Exception as ex:
            errors.append(f"{idx['ticker']}: {ex}")

    stocks = []
    for s in stocks_cfg:
        try:
            block = stock_block(clean_daily(data[s["ticker"]]), s["ticker"], s["name"])
            if block:
                stocks.append(block)
            else:
                errors.append(f"{s['ticker']}: insufficient history")
        except Exception as ex:
            errors.append(f"{s['ticker']}: {ex}")
    out["stocks"] = stocks
    out["errors"] = errors

    if "hsi" not in out or not stocks:
        print(f"ERROR: core data missing (hsi={('hsi' in out)}, stocks={len(stocks)})", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: {len(stocks)}/{len(stocks_cfg)} stocks, {len(errors)} errors -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

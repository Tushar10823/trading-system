"""
NSE intraday bars via Yahoo Finance (.NS suffix).

Read-only — never places orders. No broker keys required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Yahoo intraday history is limited; scale lookback to interval.
_LOOKBACK_DAYS = {1: 7, 5: 10, 15: 30, 30: 60}


def to_nse_symbol(symbol: str) -> str:
    sym = symbol.upper().strip()
    if sym.endswith(".NS") or sym.endswith(".BO"):
        return sym
    return f"{sym}.NS"


def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.reset_index()
    date_col = "Datetime" if "Datetime" in out.columns else "Date"
    out = out.rename(columns={date_col: "date"})
    out["date"] = pd.to_datetime(out["date"], utc=True)
    out = out[["date", "Open", "High", "Low", "Close", "Volume"]].rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    return out.sort_values("date").reset_index(drop=True)


def fetch_intraday_bars(
    symbol: str,
    *,
    minutes: int = 5,
    lookback_days: int = 10,
    min_bars: int = 40,
) -> pd.DataFrame:
    """
    Fetch 1/5/15/30-min OHLCV bars for an NSE symbol (Yahoo .NS ticker).
    """
    if minutes not in (1, 5, 15, 30):
        raise ValueError("minutes must be 1, 5, 15, or 30")

    ysym = to_nse_symbol(symbol)
    days = max(lookback_days, _LOOKBACK_DAYS.get(minutes, lookback_days))
    period = f"{days}d"
    interval = f"{minutes}m"

    df = yf.Ticker(ysym).history(period=period, interval=interval, auto_adjust=True)
    df = _normalize_history(df)
    if df.empty:
        raise RuntimeError(
            f"No {minutes}-min bars returned for {ysym}. "
            "Market may be closed or symbol unsupported on Yahoo."
        )

    if len(df) < min_bars:
        raise RuntimeError(
            f"Only {len(df)} {minutes}-min bars for {ysym}; need >= {min_bars} "
            "for indicators. Try a more liquid symbol or larger lookback."
        )
    return df


def is_nse_market_hours() -> bool:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return (9 * 60 + 15) <= mins < (15 * 60 + 30)


def minutes_to_nse_close() -> int:
    now = datetime.now(IST)
    close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return max(int((close - now).total_seconds() // 60), 0)

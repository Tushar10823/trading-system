"""
Shared Alpaca market-data helpers (paper keys, IEX feed).

Read-only — never places orders.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit


def load_keys() -> tuple[str, str]:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)
    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    base_url = os.getenv(
        "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
    ).strip()

    if not api_key or not secret_key:
        print("Missing Alpaca keys in .env")
        sys.exit(1)
    if "paper-api.alpaca.markets" not in base_url:
        print("ERROR: ALPACA_BASE_URL must be the paper endpoint.")
        sys.exit(1)
    return api_key, secret_key


def _normalize_bars(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    out = df.reset_index()
    if "symbol" in out.columns:
        out = out[out["symbol"] == symbol].copy()
    out = out.rename(columns={"timestamp": "date"})
    out = out[["date", "open", "high", "low", "close", "volume"]].sort_values("date")
    return out.reset_index(drop=True)


def fetch_daily_bars(
    symbol: str,
    *,
    trading_days: int | None = None,
    calendar_days: int | None = None,
) -> pd.DataFrame:
    """
    Fetch daily OHLCV bars from Alpaca IEX.

    Provide either trading_days (tail N bars) or calendar_days (lookback window).
    """
    if trading_days is None and calendar_days is None:
        trading_days = 90

    api_key, secret_key = load_keys()
    client = StockHistoricalDataClient(api_key, secret_key)

    end = datetime.now(timezone.utc)
    if calendar_days is not None:
        start = end - timedelta(days=calendar_days)
    else:
        assert trading_days is not None
        start = end - timedelta(days=int(trading_days * 1.7) + 10)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        limit=10000,
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request).df
    if bars.empty:
        raise RuntimeError(f"No bars returned for {symbol}")

    df = _normalize_bars(bars, symbol)

    if trading_days is not None and calendar_days is None:
        df = df.tail(trading_days).reset_index(drop=True)

    return df


def fetch_intraday_bars(
    symbol: str,
    *,
    minutes: int = 5,
    lookback_days: int = 5,
    min_bars: int = 80,
) -> pd.DataFrame:
    """
    Fetch 1/5/15/30-min OHLCV bars from Alpaca IEX for intraday signals.
    """
    if minutes not in (1, 5, 15, 30):
        raise ValueError("minutes must be 1, 5, 15, or 30")

    api_key, secret_key = load_keys()
    client = StockHistoricalDataClient(api_key, secret_key)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    timeframe = TimeFrame(minutes, TimeFrameUnit.Minute)

    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=10000,
        feed=DataFeed.IEX,
    )
    bars = client.get_stock_bars(request).df
    if bars.empty:
        raise RuntimeError(
            f"No {minutes}-min bars returned for {symbol}. "
            "Market may be closed or symbol unsupported on IEX."
        )

    df = _normalize_bars(bars, symbol)
    if len(df) < min_bars:
        raise RuntimeError(
            f"Only {len(df)} {minutes}-min bars for {symbol}; need >= {min_bars} "
            "for indicators. Try a more liquid symbol or larger lookback."
        )
    return df

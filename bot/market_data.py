"""
Shared Alpaca market-data helpers (paper keys, IEX feed).

Read-only — never places orders.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockBarsRequest,
    StockLatestQuoteRequest,
    StockLatestTradeRequest,
)
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


_PRICE_CACHE: dict[str, float] = {}
_PRICE_CACHE_AT = 0.0
_PRICE_CLIENT: StockHistoricalDataClient | None = None
_PRICE_TTL = 1.0


def _price_client() -> StockHistoricalDataClient:
    global _PRICE_CLIENT
    if _PRICE_CLIENT is None:
        api_key, secret_key = load_keys()
        _PRICE_CLIENT = StockHistoricalDataClient(api_key, secret_key)
    return _PRICE_CLIENT


def _as_map(payload: object) -> dict:
    if not payload:
        return {}
    data = payload if isinstance(payload, dict) else getattr(payload, "data", payload)
    if not hasattr(data, "items"):
        return {}
    return {str(k).upper(): v for k, v in data.items()}


def _mid_quote(quote: object) -> float | None:
    try:
        bid = float(getattr(quote, "bid_price", 0) or 0)
        ask = float(getattr(quote, "ask_price", 0) or 0)
    except (TypeError, ValueError):
        return None
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    if ask > 0:
        return ask
    if bid > 0:
        return bid
    return None


def fetch_latest_prices(symbols: list[str]) -> dict[str, float]:
    """Live IEX mark: tight quote mid, otherwise last trade."""
    global _PRICE_CACHE_AT
    tickers = sorted({str(s).upper() for s in symbols if s})
    if not tickers:
        return {}
    now = time.time()
    if now - _PRICE_CACHE_AT < _PRICE_TTL and all(s in _PRICE_CACHE for s in tickers):
        return {s: _PRICE_CACHE[s] for s in tickers}
    client = _price_client()
    quotes = {}
    trades = {}
    try:
        quotes = _as_map(
            client.get_stock_latest_quote(
                StockLatestQuoteRequest(symbol_or_symbols=tickers, feed=DataFeed.IEX)
            )
        )
    except Exception:
        pass
    try:
        trades = _as_map(
            client.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=tickers, feed=DataFeed.IEX)
            )
        )
    except Exception:
        pass
    out: dict[str, float] = {}
    for sym in tickers:
        quote = quotes.get(sym)
        trade = trades.get(sym)
        last = None
        if trade is not None:
            try:
                last = float(trade.price)
            except (TypeError, ValueError, AttributeError):
                last = None
        mid = _mid_quote(quote) if quote is not None else None
        mark = last
        if mid is not None and quote is not None:
            try:
                bid = float(getattr(quote, "bid_price", 0) or 0)
                ask = float(getattr(quote, "ask_price", 0) or 0)
            except (TypeError, ValueError):
                bid = ask = 0.0
            if bid > 0 and ask > 0 and (ask - bid) / mid <= 0.0015:
                mark = mid
        if mark is None:
            mark = mid
        if mark is not None:
            out[sym] = mark
    if out:
        _PRICE_CACHE.update(out)
        _PRICE_CACHE_AT = now
    return {s: _PRICE_CACHE[s] for s in tickers if s in _PRICE_CACHE}

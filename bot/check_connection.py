"""
Phase 1 — Verify Alpaca paper trading API connectivity.

Loads keys from bot/.env, connects to the paper API, fetches the last 30
daily bars for AAPL, and prints them.

PAPER TRADING ONLY. This script never places orders.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient


def load_config() -> tuple[str, str, str]:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)

    api_key = os.getenv("ALPACA_API_KEY", "").strip()
    secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
    base_url = os.getenv(
        "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
    ).strip()

    if not api_key or not secret_key:
        print("Missing ALPACA_API_KEY or ALPACA_SECRET_KEY.")
        print(f"Create {env_path} from .env.example and add your paper keys.")
        sys.exit(1)

    if "paper-api.alpaca.markets" not in base_url:
        # Safety: refuse non-paper base URLs so we never silently hit live.
        print("ERROR: ALPACA_BASE_URL is not the paper trading endpoint.")
        print(f"  Got:      {base_url}")
        print("  Expected: https://paper-api.alpaca.markets")
        print("Refusing to continue. Paper trading only for this project.")
        sys.exit(1)

    return api_key, secret_key, base_url


def main() -> None:
    api_key, secret_key, base_url = load_config()

    print("=" * 60)
    print("Alpaca connection check")
    print(f"Account mode: PAPER")
    print(f"Base URL:     {base_url}")
    print("=" * 60)

    # paper=True forces paper trading account even if URL were wrong later.
    trading = TradingClient(api_key, secret_key, paper=True)
    account = trading.get_account()
    print(f"Account status: {account.status}")
    print(f"Account ID:     {account.id}")
    print(f"Equity:         ${float(account.equity):,.2f}")
    print(f"Buying power:   ${float(account.buying_power):,.2f}")
    print()

    data = StockHistoricalDataClient(api_key, secret_key)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=60)  # buffer for weekends/holidays → ~30 trading days
    # Free Alpaca accounts get IEX, not SIP. Using SIP causes 403 on recent bars.
    request = StockBarsRequest(
        symbol_or_symbols="AAPL",
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        limit=30,
        feed=DataFeed.IEX,
    )
    bars = data.get_stock_bars(request).df

    if bars.empty:
        print("No bars returned for AAPL. Check API access / market data plan.")
        sys.exit(1)

    display = bars.reset_index()
    # Keep the most recent 30 rows if more came back
    if len(display) > 30:
        display = display.tail(30)

    print(f"Last {len(display)} daily bars for AAPL:")
    print(display.to_string(index=False))
    print()
    print("Connection OK. Phase 1 data pull succeeded.")


if __name__ == "__main__":
    main()

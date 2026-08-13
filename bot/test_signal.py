"""
Phase 3 test — sample BUY/SELL/HOLD signal for a symbol (default: AAPL).

Usage:
  python test_signal.py
  python test_signal.py MSFT

PAPER / read-only: fetches market data only; never places orders.
"""

from __future__ import annotations

import sys

from market_data import fetch_daily_bars
from signal_engine import generate_signal, format_signal_report


def main() -> None:
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "AAPL").upper()

    print(f"Phase 3 - Signal combiner sample ({symbol})")
    print("Data feed: IEX | Account mode: PAPER keys | No orders placed")
    print()

    df = fetch_daily_bars(symbol, trading_days=90)
    close = float(df["close"].iloc[-1])
    payload = generate_signal(df)
    print(format_signal_report(symbol, close, payload))
    print("Phase 3 sample complete.")


if __name__ == "__main__":
    main()

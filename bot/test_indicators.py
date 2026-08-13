"""
Phase 2 test — run indicators on a symbol's last ~90 trading days and print a table.

PAPER / read-only: fetches market data only; never places orders.
"""

from __future__ import annotations

import sys

from indicators import evaluate_all, results_table
from market_data import fetch_daily_bars


def main() -> None:
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "AAPL").upper()
    print("=" * 60)
    print(f"Phase 2 - Indicator test ({symbol}, last ~90 daily bars)")
    print("Data feed: IEX (free-tier safe) | Account mode: PAPER keys")
    print("=" * 60)

    df = fetch_daily_bars(symbol, trading_days=90)
    print(f"Bars loaded: {len(df)}")
    print(f"Range:      {df['date'].iloc[0]} -> {df['date'].iloc[-1]}")
    print(f"Last close: {float(df['close'].iloc[-1]):.2f}")
    print()

    results = evaluate_all(df)
    table = results_table(results)
    print(table.to_string(index=False))
    print()
    print("Label legend: bullish | bearish | neutral")
    print("Phase 2 indicator run complete.")


if __name__ == "__main__":
    main()

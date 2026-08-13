"""
Phase 4 — Backtest the signal engine on historical daily bars.

Rules (kept simple on purpose):
  - Whole shares only, one position at a time
  - No leverage, no shorting
  - BUY when flat + signal is BUY (fill at that day's close)
  - SELL when holding + signal is SELL (fill at that day's close)
  - HOLD does nothing
  - Open position at end is marked to the last close for equity stats;
    closed-trade metrics use completed round-trips only

Usage:
  python backtest.py              # AAPL and MSFT, ~2 years
  python backtest.py AAPL TSLA    # custom symbols

PAPER / read-only market data. Simulated trades only — nothing sent to Alpaca.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from market_data import fetch_daily_bars
from signal_engine import generate_signal

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

INITIAL_CASH = 100_000.0
# Bars needed before indicators are reliable (MACD/EMA/BB warm-up)
WARMUP_BARS = 40
# ~2 years of calendar lookback
LOOKBACK_CALENDAR_DAYS = 730
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


@dataclass
class OpenPosition:
    entry_date: Any
    entry_price: float
    shares: int
    entry_score: float
    entry_reasoning: str


def run_backtest(df: pd.DataFrame, symbol: str) -> dict[str, Any]:
    cash = INITIAL_CASH
    position: OpenPosition | None = None
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = []

    for i in range(len(df)):
        if i < WARMUP_BARS:
            # Still build equity as cash-only during warm-up
            equity_curve.append(cash)
            continue

        window = df.iloc[: i + 1].reset_index(drop=True)
        row = df.iloc[i]
        close = float(row["close"])
        date = row["date"]

        try:
            payload = generate_signal(window)
        except Exception as exc:  # noqa: BLE001 — skip thin/bad windows
            equity = cash + (position.shares * close if position else 0.0)
            equity_curve.append(equity)
            print(f"  skip {date}: {exc}")
            continue

        signal = payload["signal"]
        score = float(payload["score"])
        reasoning = payload["reasoning"]

        if position is None and signal == "BUY":
            shares = int(cash // close)
            if shares > 0:
                cost = shares * close
                cash -= cost
                position = OpenPosition(
                    entry_date=date,
                    entry_price=close,
                    shares=shares,
                    entry_score=score,
                    entry_reasoning=reasoning,
                )

        elif position is not None and signal == "SELL":
            proceeds = position.shares * close
            pnl = proceeds - (position.shares * position.entry_price)
            pnl_pct = (close / position.entry_price - 1.0) * 100.0
            cash += proceeds
            trades.append(
                {
                    "symbol": symbol,
                    "entry_date": position.entry_date,
                    "exit_date": date,
                    "entry_price": round(position.entry_price, 4),
                    "exit_price": round(close, 4),
                    "shares": position.shares,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 3),
                    "entry_score": position.entry_score,
                    "exit_score": score,
                    "entry_reasoning": position.entry_reasoning,
                    "exit_reasoning": reasoning,
                }
            )
            position = None

        equity = cash + (position.shares * close if position else 0.0)
        equity_curve.append(equity)

    # Mark-to-market if still holding (not a closed trade)
    final_close = float(df.iloc[-1]["close"])
    final_equity = cash + (position.shares * final_close if position else 0.0)
    open_position = None
    if position is not None:
        open_position = {
            "entry_date": position.entry_date,
            "entry_price": position.entry_price,
            "shares": position.shares,
            "mark_price": final_close,
            "unrealized_pnl": round(
                position.shares * (final_close - position.entry_price), 2
            ),
        }

    return {
        "symbol": symbol,
        "trades": trades,
        "equity_curve": equity_curve,
        "final_equity": final_equity,
        "open_position": open_position,
        "df": df,
    }


def max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = (eq - peak) / peak if peak else 0.0
        max_dd = min(max_dd, dd)
    return max_dd * 100.0  # percent


def summarize(result: dict[str, Any]) -> dict[str, Any]:
    df: pd.DataFrame = result["df"]
    trades: list[dict[str, Any]] = result["trades"]
    equity_curve: list[float] = result["equity_curve"]

    # Strategy return from first post-warm-up equity baseline
    start_equity = INITIAL_CASH
    end_equity = float(result["final_equity"])
    strategy_return = (end_equity / start_equity - 1.0) * 100.0

    # Buy & hold over the tradeable window (after warm-up)
    bh_start = float(df.iloc[WARMUP_BARS]["close"])
    bh_end = float(df.iloc[-1]["close"])
    buy_hold_return = (bh_end / bh_start - 1.0) * 100.0

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = (len(wins) / len(pnls) * 100.0) if pnls else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    avg_trade = sum(pnls) / len(pnls) if pnls else 0.0

    return {
        "symbol": result["symbol"],
        "bars": len(df),
        "start": str(df.iloc[0]["date"]),
        "end": str(df.iloc[-1]["date"]),
        "trades": len(trades),
        "win_rate_pct": round(win_rate, 2),
        "avg_trade_pnl": round(avg_trade, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "strategy_return_pct": round(strategy_return, 2),
        "buy_hold_return_pct": round(buy_hold_return, 2),
        "vs_buy_hold_pct": round(strategy_return - buy_hold_return, 2),
        "max_drawdown_pct": round(max_drawdown(equity_curve), 2),
        "final_equity": round(end_equity, 2),
        "open_position": result["open_position"],
    }


def print_summary(stats: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"Backtest: {stats['symbol']}")
    print(f"Range:    {stats['start']} -> {stats['end']}  ({stats['bars']} bars)")
    print("-" * 60)
    print(f"Closed trades:     {stats['trades']}")
    print(f"Win rate:          {stats['win_rate_pct']:.2f}%")
    print(f"Avg trade P&L:     ${stats['avg_trade_pnl']:,.2f}")
    print(f"Avg win:           ${stats['avg_win']:,.2f}")
    print(f"Avg loss:          ${stats['avg_loss']:,.2f}")
    print(f"Strategy return:   {stats['strategy_return_pct']:.2f}%")
    print(f"Buy & hold return: {stats['buy_hold_return_pct']:.2f}%")
    print(f"vs buy & hold:     {stats['vs_buy_hold_pct']:+.2f} pp")
    print(f"Max drawdown:      {stats['max_drawdown_pct']:.2f}%")
    print(f"Final equity:      ${stats['final_equity']:,.2f}  (start ${INITIAL_CASH:,.0f})")
    if stats["open_position"]:
        op = stats["open_position"]
        print(
            f"Open position:     {op['shares']} sh @ {op['entry_price']:.2f} "
            f"(mark {op['mark_price']:.2f}, uPnL ${op['unrealized_pnl']:,.2f})"
        )
    print("=" * 60)


def save_trades_csv(symbol: str, trades: list[dict[str, Any]]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"backtest_trades_{symbol.upper()}.csv"
    pd.DataFrame(trades).to_csv(path, index=False)
    return path


def backtest_symbol(symbol: str) -> dict[str, Any]:
    print(f"\nFetching ~2y daily bars for {symbol} (IEX)...")
    df = fetch_daily_bars(symbol, calendar_days=LOOKBACK_CALENDAR_DAYS)
    print(f"Loaded {len(df)} bars. Running signal engine day-by-day...")
    result = run_backtest(df, symbol)
    stats = summarize(result)
    print_summary(stats)
    csv_path = save_trades_csv(symbol, result["trades"])
    print(f"Trade log saved: {csv_path}")
    return stats


def main() -> None:
    symbols = [s.upper() for s in sys.argv[1:]] or ["AAPL", "MSFT"]
    print("Phase 4 - Backtest")
    print(
        f"Initial cash ${INITIAL_CASH:,.0f} | warmup {WARMUP_BARS} bars | "
        f"lookback {LOOKBACK_CALENDAR_DAYS}d | whole shares, long-only"
    )
    print("Simulated only - no live/paper orders placed.")

    all_stats = []
    for symbol in symbols:
        all_stats.append(backtest_symbol(symbol))

    if len(all_stats) > 1:
        print("\nComparison")
        print("-" * 60)
        rows = [
            [
                s["symbol"],
                s["trades"],
                f"{s['win_rate_pct']:.1f}%",
                f"{s['strategy_return_pct']:.2f}%",
                f"{s['buy_hold_return_pct']:.2f}%",
                f"{s['vs_buy_hold_pct']:+.2f}pp",
                f"{s['max_drawdown_pct']:.2f}%",
            ]
            for s in all_stats
        ]
        table = pd.DataFrame(
            rows,
            columns=[
                "symbol",
                "trades",
                "win_rate",
                "strategy",
                "buy_hold",
                "vs_bh",
                "max_dd",
            ],
        )
        print(table.to_string(index=False))

    print("\nPhase 4 backtest complete.")


if __name__ == "__main__":
    main()

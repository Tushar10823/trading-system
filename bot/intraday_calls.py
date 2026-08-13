"""
Intraday day-trade calls (paper research mode).

Designed for same-session trading:
  - Primary decision: 5-minute bars
  - Confirmation: 1-minute bars (blocks conflicting entries)
  - Outputs: ACTION, entry, stop-loss, take-profit
  - Tighter risk than swing mode (default 0.8% SL / 1.5% TP)

Usage:
  python intraday_calls.py
  python intraday_calls.py AAPL TSLA GOOGL
  python intraday_calls.py --loop 5

LOG ONLY by default. This script does not place orders.
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from indicators import evaluate_all
from market_data import fetch_intraday_bars
from signal_engine import combine_labels

# ---------------------------------------------------------------------------
# Intraday tunables
# ---------------------------------------------------------------------------

# Slightly more sensitive than swing (daily) mode so intraday setups can fire
INTRADAY_BUY_THRESHOLD = 1.0
INTRADAY_SELL_THRESHOLD = -1.0

# Early in / early out scalp (tighter than swing)
STOP_LOSS_PCT = 0.004   # 0.4%
TAKE_PROFIT_PCT = 0.007  # 0.7%
# Stay in the call this long before reversing (unless SL/TP hits)
HOLD_MINUTES = 30
FLATTEN_MINUTES = 20

DEFAULT_WATCHLIST = ["AAPL", "TSLA", "GOOGL", "MSFT", "NVDA", "AMZN", "META", "SPY"]

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
CALL_LOG = OUTPUT_DIR / "intraday_calls.csv"
ET = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")


def is_regular_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= mins < (16 * 60)


def minutes_to_close() -> int:
    now = datetime.now(ET)
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return int((close - now).total_seconds() // 60)


def score_frame(df: pd.DataFrame) -> dict[str, Any]:
    """Score using indicator labels, with intraday thresholds."""
    results = evaluate_all(df)
    # Temporarily reuse combiner math, then re-threshold for intraday
    combined = combine_labels(results)
    score = float(combined["score"])
    if score >= INTRADAY_BUY_THRESHOLD:
        signal = "BUY"
    elif score <= INTRADAY_SELL_THRESHOLD:
        signal = "SELL"
    else:
        signal = "HOLD"
    combined["signal"] = signal
    combined["buy_threshold"] = INTRADAY_BUY_THRESHOLD
    combined["sell_threshold"] = INTRADAY_SELL_THRESHOLD
    combined["indicators"] = results
    return combined


def decide_call(primary: dict[str, Any], confirm: dict[str, Any]) -> tuple[str, str]:
    """
    Early-entry / early-out on 30m primary, 5m confirm:
      - BUY: 30m BUY, 5m not opposite
      - SELL: both 30m and 5m SELL (confirmed short)
      - EXIT: 30m SELL but 5m not SELL — flatten longs only
    """
    p, c = primary["signal"], confirm["signal"]
    if p == "BUY" and c == "SELL":
        return "HOLD", "blocked: 30m BUY vs 5m SELL"
    if p == "SELL" and c == "BUY":
        return "HOLD", "blocked: 30m SELL vs 5m BUY"
    if p == "HOLD":
        return "HOLD", "5m not decisive"
    if p == "BUY" and c == "BUY":
        return "BUY", "BUY confirmed: 30m+5m"
    if p == "BUY":
        return "BUY", "BUY: 30m BUY (5m not opposing)"
    if p == "SELL" and c == "SELL":
        return "SELL", "SELL confirmed: 30m+5m (short)"
    if p == "SELL":
        return "EXIT", "EXIT longs only: 30m SELL, 5m not confirmed"
    return "HOLD", "no setup"


def trade_plan(action: str, price: float) -> dict[str, float | str]:
    px = round(price, 2)
    if action == "BUY":
        return {
            "side": "BUY",
            "entry": px,
            "stop": round(price * (1 - STOP_LOSS_PCT), 2),
            "target": round(price * (1 + TAKE_PROFIT_PCT), 2),
        }
    if action == "SELL":
        return {
            "side": "SELL",
            "entry": px,
            "stop": round(price * (1 + STOP_LOSS_PCT), 2),
            "target": round(price * (1 - TAKE_PROFIT_PCT), 2),
        }
    if action == "EXIT":
        return {"side": "FLATTEN_LONG", "entry": px, "stop": "-", "target": "-"}
    return {"side": "-", "entry": px, "stop": "-", "target": "-"}


def analyze_symbol(symbol: str) -> dict[str, Any]:
    df30 = fetch_intraday_bars(symbol, minutes=30, lookback_days=15, min_bars=40)
    df5 = fetch_intraday_bars(symbol, minutes=5, lookback_days=10, min_bars=40)
    price = float(df30["close"].iloc[-1])

    primary = score_frame(df30)
    confirm = score_frame(df5)
    action, note = decide_call(primary, confirm)
    plan = trade_plan(action, price)

    mtc = minutes_to_close()
    if is_regular_market_hours() and mtc <= FLATTEN_MINUTES and action in ("BUY", "SELL"):
        action = "EXIT" if action == "SELL" else "HOLD"
        if action == "EXIT":
            note = f"flatten window {mtc}m to close — no new sells; cover/exit"
        else:
            note = f"no new buys - {mtc}m to close (flatten window)"
        plan = trade_plan(action, price)

    wait_min = 0 if action in ("HOLD", "EXIT") else min(HOLD_MINUTES, max(mtc, 0) if is_regular_market_hours() else HOLD_MINUTES)
    if action in ("BUY", "SELL") and wait_min < 5:
        wait_min = max(wait_min, 0)
    wait_until_dt = datetime.now(IST) + timedelta(minutes=wait_min) if wait_min else None
    wait_until = wait_until_dt.strftime("%H:%M IST") if wait_until_dt else "-"
    wait_until_iso = wait_until_dt.isoformat() if wait_until_dt else ""

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "action": action,
        "confidence": note,
        "score_5m": confirm["score"],
        "signal_5m": confirm["signal"],
        "score_1m": primary["score"],
        "signal_1m": primary["signal"],
        "score_30m": primary["score"],
        "signal_30m": primary["signal"],
        "side": plan["side"],
        "entry": plan["entry"],
        "stop": plan["stop"],
        "target": plan["target"],
        "wait_min": wait_min,
        "wait_until": wait_until,
        "wait_until_iso": wait_until_iso,
        "reasoning_5m": primary["reasoning"],
    }


def log_calls(rows: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = [
        "timestamp_utc",
        "symbol",
        "price",
        "action",
        "confidence",
        "score_5m",
        "signal_5m",
        "score_1m",
        "signal_1m",
        "side",
        "entry",
        "stop",
        "target",
        "wait_min",
        "wait_until",
    ]
    write_header = not CALL_LOG.exists()
    with CALL_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        ts = datetime.now(timezone.utc).isoformat()
        for r in rows:
            w.writerow(
                {
                    "timestamp_utc": ts,
                    "symbol": r["symbol"],
                    "price": r["price"],
                    "action": r["action"],
                    "confidence": r["confidence"],
                    "score_5m": r["score_5m"],
                    "signal_5m": r["signal_5m"],
                    "score_1m": r["score_1m"],
                    "signal_1m": r["signal_1m"],
                    "side": r["side"],
                    "entry": r["entry"],
                    "stop": r["stop"],
                    "target": r["target"],
                    "wait_min": r.get("wait_min", HOLD_MINUTES),
                    "wait_until": r.get("wait_until", "-"),
                }
            )


def print_calls(rows: list[dict[str, Any]]) -> None:
    now = datetime.now(IST)
    print("=" * 72)
    print("INTRADAY CALLS (paper research) - not financial advice")
    print(f"Time IST: {now.strftime('%Y-%m-%d %H:%M IST')} | market_open={is_regular_market_hours()}")
    if is_regular_market_hours():
        print(
            f"Minutes to close: {minutes_to_close()} | "
            f"no new buys/sells inside {FLATTEN_MINUTES}m of close"
        )
    print(
        f"Rules: 30m chart + 5m confirm | BUY / SELL | hold {HOLD_MINUTES}m | "
        f"SL {STOP_LOSS_PCT:.1%} / TP {TAKE_PROFIT_PCT:.1%}"
    )
    print("=" * 72)

    table = pd.DataFrame(
        [
            {
                "symbol": r["symbol"],
                "price": r["price"],
                "tv": r["action"] if r["action"] in ("BUY", "SELL", "EXIT") else "-",
                "action": r["action"],
                "30m": f"{r.get('signal_30m', r.get('signal_1m', ''))}({r.get('score_30m', r.get('score_1m', 0)):+.0f})",
                "5m": f"{r['signal_5m']}({r['score_5m']:+.0f})",
                "entry": r["entry"],
                "stop": r["stop"],
                "target": r["target"],
                "wait": f"{r.get('wait_min', 0)}m until {r.get('wait_until', '-')}",
                "note": r["confidence"],
            }
            for r in rows
        ]
    )
    print(table.to_string(index=False))
    print()
    actionable = [r for r in rows if r["action"] in ("BUY", "SELL", "EXIT")]
    if not actionable:
        print("No actionable day-trade entries right now (all HOLD).")
    else:
        print("Actionable (TradingView paper):")
        for r in actionable:
            if r["action"] == "BUY":
                how = "BUY  (Buy, SL below, TP above)"
            elif r["action"] == "SELL":
                how = "SELL (Sell/short, SL above, TP below)"
            else:
                how = "EXIT (close long; do not open short)"
            print(
                f"  {how:40} {r['symbol']:5} @ {r['entry']} | "
                f"stop {r['stop']} | target {r['target']} | "
                f"wait {r.get('wait_min', HOLD_MINUTES)}m (don't reverse before {r.get('wait_until', '-')})"
            )
    print(f"\nLogged -> {CALL_LOG}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Intraday day-trade calls")
    p.add_argument("symbols", nargs="*", help="Tickers (default watchlist)")
    p.add_argument("--loop", type=int, default=0, help="Repeat every N minutes (0=once)")
    p.add_argument("--cycles", type=int, default=0, help="Stop after N loops (0=forever)")
    return p.parse_args()


def run_once(symbols: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            rows.append(analyze_symbol(sym))
            print(f"  scanned {sym}")
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {sym}: {exc}")
    if rows:
        log_calls(rows)
        print_calls(rows)
    return rows


def main() -> None:
    args = parse_args()
    symbols = [s.upper() for s in args.symbols] or DEFAULT_WATCHLIST
    print("Building intraday calls...")
    if args.loop <= 0:
        run_once(symbols)
        return

    cycle = 0
    while True:
        cycle += 1
        print(f"\n----- Call cycle {cycle} -----")
        run_once(symbols)
        if args.cycles and cycle >= args.cycles:
            break
        print(f"Sleeping {args.loop} minute(s)...")
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()

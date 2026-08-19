"""
Intraday day-trade calls for NSE stocks (paper research mode).

Uses Yahoo Finance (.NS) for 30m + 5m bars and the same signal engine as US scans.
NSE session: 09:15–15:30 IST.

Usage:
  python india_intraday_calls.py
  python india_intraday_calls.py RELIANCE TCS HDFCBANK
  python india_intraday_calls.py --loop 30
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from india_market_data import (
    fetch_intraday_bars,
    is_nse_market_hours,
    minutes_to_nse_close,
    to_nse_symbol,
)
from intraday_calls import (
    FLATTEN_MINUTES,
    HOLD_MINUTES,
    IST,
    atr_value,
    decide_call,
    score_frame,
    sl_tp_pct,
    trade_plan,
)

DEFAULT_WATCHLIST = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "BHARTIARTL",
    "ITC",
    "SBIN",
    "LT",
    "KOTAKBANK",
    "HINDUNILVR",
    "AXISBANK",
    "BAJFINANCE",
    "MARUTI",
    "WIPRO",
]

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
CALL_LOG = OUTPUT_DIR / "india_intraday_calls.csv"


def analyze_symbol(symbol: str) -> dict[str, Any]:
    sym = symbol.upper().strip().removesuffix(".NS")
    df30 = fetch_intraday_bars(sym, minutes=30, lookback_days=60, min_bars=40)
    df5 = fetch_intraday_bars(sym, minutes=5, lookback_days=10, min_bars=40)
    price = float(df30["close"].iloc[-1])

    primary = score_frame(df30)
    confirm = score_frame(df5)
    action, note = decide_call(primary, confirm)
    atr = atr_value(df30)
    stop_pct, target_pct = sl_tp_pct(price, atr)
    plan = trade_plan(action, price, stop_pct, target_pct)

    mtc = minutes_to_nse_close()
    if is_nse_market_hours() and mtc <= FLATTEN_MINUTES and action in ("BUY", "SELL"):
        action = "EXIT" if action == "SELL" else "HOLD"
        if action == "EXIT":
            note = f"flatten window {mtc}m to NSE close — no new sells; cover/exit"
        else:
            note = f"no new buys - {mtc}m to NSE close (flatten window)"
        plan = trade_plan(action, price, stop_pct, target_pct)

    wait_min = (
        0
        if action in ("HOLD", "EXIT")
        else min(HOLD_MINUTES, max(mtc, 0) if is_nse_market_hours() else HOLD_MINUTES)
    )
    wait_until_dt = datetime.now(IST) + timedelta(minutes=wait_min) if wait_min else None
    wait_until = wait_until_dt.strftime("%H:%M IST") if wait_until_dt else "-"
    wait_until_iso = wait_until_dt.isoformat() if wait_until_dt else ""

    target_inr = round(abs(price * target_pct), 2)
    stop_inr = round(abs(price * stop_pct), 2)

    return {
        "symbol": sym,
        "yahoo": to_nse_symbol(sym),
        "price": round(price, 2),
        "action": action,
        "confidence": note,
        "score_5m": confirm["score"],
        "signal_5m": confirm["signal"],
        "score_30m": primary["score"],
        "signal_30m": primary["signal"],
        "side": plan["side"],
        "entry": plan["entry"],
        "stop": plan["stop"],
        "target": plan["target"],
        "wait_min": wait_min,
        "wait_until": wait_until,
        "wait_until_iso": wait_until_iso,
        "atr": round(atr, 4),
        "atr_pct": round(atr / price * 100, 3) if price else 0,
        "stop_pct": round(stop_pct * 100, 3),
        "target_pct": round(target_pct * 100, 3),
        "stop_inr": stop_inr,
        "target_inr": target_inr,
        "target_on_10": round(target_inr * 10, 2),
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
        "score_30m",
        "signal_30m",
        "side",
        "entry",
        "stop",
        "target",
        "atr_pct",
        "stop_pct",
        "target_pct",
        "target_inr",
        "target_on_10",
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
            w.writerow({"timestamp_utc": ts, **{k: r.get(k, "") for k in fields if k != "timestamp_utc"}})


def print_calls(rows: list[dict[str, Any]]) -> None:
    now = datetime.now(IST)
    print("=" * 80)
    print("NSE INTRADAY CALLS (paper research, Yahoo .NS) — not financial advice")
    print(
        f"Time IST: {now.strftime('%Y-%m-%d %H:%M IST')} | "
        f"nse_open={is_nse_market_hours()}"
    )
    if is_nse_market_hours():
        print(
            f"Minutes to NSE close: {minutes_to_nse_close()} | "
            f"no new buys/sells inside {FLATTEN_MINUTES}m of close"
        )
    print(
        f"Rules: 30m+5m both agree | hold {HOLD_MINUTES}m | "
        f"SL/TP from 30m ATR"
    )
    print("=" * 80)

    table = pd.DataFrame(
        [
            {
                "symbol": r["symbol"],
                "price": r["price"],
                "action": r["action"],
                "30m": f"{r['signal_30m']}({r['score_30m']:+.0f})",
                "5m": f"{r['signal_5m']}({r['score_5m']:+.0f})",
                "entry": r["entry"],
                "stop": r["stop"],
                "target": r["target"],
                "atr%": r["atr_pct"],
                "tp%": r["target_pct"],
                "tp₹/sh": r["target_inr"],
                "tp₹×10": r["target_on_10"],
                "wait": f"{r['wait_min']}m → {r['wait_until']}",
            }
            for r in rows
        ]
    )
    print(table.to_string(index=False))
    print()

    actionable = [r for r in rows if r["action"] in ("BUY", "SELL", "EXIT")]
    if not actionable:
        print("No actionable NSE entries right now (all HOLD).")
    else:
        print("Actionable:")
        for r in actionable:
            print(
                f"  {r['action']:4} {r['symbol']:12} @ ₹{r['entry']} | "
                f"stop ₹{r['stop']} ({r['stop_pct']}%) | "
                f"target ₹{r['target']} ({r['target_pct']}%, ₹{r['target_inr']}/sh, "
                f"₹{r['target_on_10']} on 10) | wait {r['wait_until']}"
            )
    print(f"\nLogged -> {CALL_LOG}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NSE intraday day-trade calls (paper)")
    p.add_argument("symbols", nargs="*", help="NSE tickers (default Nifty liquid set)")
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
    symbols = [s.upper().removesuffix(".NS") for s in args.symbols] or DEFAULT_WATCHLIST
    print("Building NSE intraday calls...")
    if args.loop <= 0:
        run_once(symbols)
        return

    cycle = 0
    while True:
        cycle += 1
        print(f"\n----- NSE call cycle {cycle} -----")
        run_once(symbols)
        if args.cycles and cycle >= args.cycles:
            break
        print(f"Sleeping {args.loop} minute(s)...")
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()

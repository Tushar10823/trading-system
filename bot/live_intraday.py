"""
Intraday live signal loop — 1-min or 5-min bars, refresh every 1-5 minutes.

Default: LOG ONLY (no orders). Pass --auto-trade to place PAPER orders.

Usage:
  python live_intraday.py --symbol AAPL --bar 5 --interval 5 --once
  python live_intraday.py --symbol AAPL --bar 1 --interval 1
  python live_intraday.py --symbol AAPL --bar 5 --interval 5 --cycles 3
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from market_data import fetch_intraday_bars, load_keys
from signal_engine import format_signal_report, generate_signal

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
SIGNAL_LOG = OUTPUT_DIR / "live_intraday_signals.csv"
TRADE_LOG = OUTPUT_DIR / "paper_trades.csv"
BUY_POWER_FRACTION = 0.25  # smaller size for intraday paper tests
ET = ZoneInfo("America/New_York")

SIGNAL_FIELDS = [
    "timestamp_utc",
    "symbol",
    "bar_minutes",
    "account_mode",
    "market_open",
    "close",
    "signal",
    "score",
    "ema_label",
    "rsi_label",
    "macd_label",
    "bb_label",
    "volume_label",
    "reasoning",
    "auto_trade",
    "order_id",
    "order_status",
]


def is_regular_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def append_csv(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fieldnames})


def current_position_qty(client: TradingClient, symbol: str) -> float:
    try:
        return float(client.get_open_position(symbol).qty)
    except Exception:
        return 0.0


def execute_auto_trade(
    client: TradingClient, symbol: str, signal: str, close: float
) -> dict[str, Any]:
    if signal == "HOLD":
        return {
            "order_id": "",
            "order_status": "skipped",
            "notes": "HOLD - no order",
            "side": "",
            "qty": 0,
        }

    qty_held = current_position_qty(client, symbol)

    if signal == "BUY":
        if qty_held > 0:
            return {
                "order_id": "",
                "order_status": "skipped",
                "notes": f"already long {qty_held}",
                "side": "",
                "qty": 0,
            }
        account = client.get_account()
        budget = float(account.buying_power) * BUY_POWER_FRACTION
        shares = int(budget // close)
        if shares < 1:
            return {
                "order_id": "",
                "order_status": "skipped",
                "notes": "insufficient BP for 1 share",
                "side": "",
                "qty": 0,
            }
        order = client.submit_order(
            MarketOrderRequest(
                symbol=symbol,
                qty=shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
        )
        return {
            "order_id": str(order.id),
            "order_status": str(order.status),
            "notes": f"bought {shares}",
            "side": "BUY",
            "qty": shares,
        }

    if signal == "SELL":
        if qty_held <= 0:
            return {
                "order_id": "",
                "order_status": "skipped",
                "notes": "no long to sell",
                "side": "",
                "qty": 0,
            }
        shares = int(qty_held)
        order = client.submit_order(
            MarketOrderRequest(
                symbol=symbol,
                qty=shares,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
        )
        return {
            "order_id": str(order.id),
            "order_status": str(order.status),
            "notes": f"sold {shares}",
            "side": "SELL",
            "qty": shares,
        }

    return {
        "order_id": "",
        "order_status": "skipped",
        "notes": f"unknown {signal}",
        "side": "",
        "qty": 0,
    }


def run_once(symbol: str, bar_minutes: int, auto_trade: bool) -> dict[str, Any]:
    api_key, secret = load_keys()
    client = TradingClient(api_key, secret, paper=True)
    account = client.get_account()
    market_open = is_regular_market_hours()

    print("=" * 60)
    print("!!! ACCOUNT MODE: PAPER !!!")
    print("Trading base URL: https://paper-api.alpaca.markets")
    print(f"Equity: ${float(account.equity):,.2f}")
    print(f"Symbol: {symbol} | bar={bar_minutes}Min | auto_trade={auto_trade}")
    print(f"US regular market hours now: {market_open}")
    print(f"Local IST: {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M IST')}")
    print("=" * 60)

    lookback = 7 if bar_minutes == 1 else 10
    df = fetch_intraday_bars(
        symbol, minutes=bar_minutes, lookback_days=lookback, min_bars=60
    )
    close = float(df["close"].iloc[-1])
    print(f"Bars loaded: {len(df)}")
    print(f"Range: {df['date'].iloc[0]} -> {df['date'].iloc[-1]}")
    print(f"Last close: {close:.4f}")
    print()

    payload = generate_signal(df)
    print(format_signal_report(symbol, close, payload))

    order_id = ""
    order_status = "log_only"
    if auto_trade:
        print("AUTO-TRADE ENABLED — PAPER orders only...")
        meta = execute_auto_trade(client, symbol, payload["signal"], close)
        order_id = meta.get("order_id", "")
        order_status = meta.get("order_status", "")
        print(f"Order: {order_status} id={order_id or '-'} notes={meta.get('notes')}")
        append_csv(
            TRADE_LOG,
            [
                "timestamp_utc",
                "symbol",
                "account_mode",
                "side",
                "qty",
                "signal",
                "score",
                "order_id",
                "order_status",
                "notes",
            ],
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "account_mode": "PAPER",
                "side": meta.get("side", ""),
                "qty": meta.get("qty", 0),
                "signal": payload["signal"],
                "score": payload["score"],
                "order_id": order_id,
                "order_status": order_status,
                "notes": f"intraday {bar_minutes}m | {meta.get('notes', '')}",
            },
        )
    else:
        print("Mode: LOG ONLY (pass --auto-trade to place paper orders)")

    labels = {i["name"]: i["label"] for i in payload.get("indicators", [])}
    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "bar_minutes": bar_minutes,
        "account_mode": "PAPER",
        "market_open": market_open,
        "close": round(close, 4),
        "signal": payload["signal"],
        "score": payload["score"],
        "ema_label": labels.get("EMA crossover", ""),
        "rsi_label": labels.get("RSI(14)", ""),
        "macd_label": labels.get("MACD", ""),
        "bb_label": labels.get("Bollinger Bands(20,2)", ""),
        "volume_label": labels.get("Volume vs 20d avg", ""),
        "reasoning": payload["reasoning"],
        "auto_trade": auto_trade,
        "order_id": order_id,
        "order_status": order_status,
    }
    append_csv(SIGNAL_LOG, SIGNAL_FIELDS, row)
    print(f"Logged -> {SIGNAL_LOG}")
    return row


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Intraday paper signal loop")
    p.add_argument("--symbol", default="AAPL")
    p.add_argument(
        "--bar",
        type=int,
        choices=[1, 5],
        default=5,
        help="Bar size in minutes (1 or 5)",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Minutes between loop cycles (1-5 recommended)",
    )
    p.add_argument("--once", action="store_true", help="Single run then exit")
    p.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Run N cycles then exit (0 = forever until Ctrl+C)",
    )
    p.add_argument(
        "--auto-trade",
        action="store_true",
        help="OPT-IN: place Alpaca PAPER orders",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    symbol = args.symbol.upper()
    interval = max(1, min(args.interval, 60))

    print("Intraday mode - PAPER only by default")
    print(f"Bars: {args.bar}Min | Loop every {interval} min | Symbol: {symbol}")
    print()

    if args.once:
        run_once(symbol, args.bar, args.auto_trade)
        print("Intraday single run complete.")
        return

    cycle = 0
    while True:
        cycle += 1
        print(f"\n----- Cycle {cycle} -----")
        try:
            run_once(symbol, args.bar, args.auto_trade)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}")
        if args.cycles and cycle >= args.cycles:
            print(f"Finished {args.cycles} cycles.")
            break
        print(f"Sleeping {interval} minute(s)... Ctrl+C to stop")
        time.sleep(interval * 60)


if __name__ == "__main__":
    main()

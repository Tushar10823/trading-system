"""
Phase 5 — Live paper signal loop (localhost).

Default: pull data, run signal engine, append to CSV. NO orders.
Only places paper trades when you pass --auto-trade explicitly.

Usage (safe first):
  python live_signal.py --symbol AAPL --once

Scheduled every 15 minutes (log only):
  python live_signal.py --symbol AAPL --interval 15

Paper trading (OPT-IN):
  python live_signal.py --symbol AAPL --once --auto-trade

Always prints PAPER vs LIVE account mode on every run.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from market_data import fetch_daily_bars, load_keys
from signal_engine import format_signal_report, generate_signal

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
SIGNAL_LOG = OUTPUT_DIR / "live_signals.csv"
TRADE_LOG = OUTPUT_DIR / "paper_trades.csv"

# Whole-share sizing: spend up to this fraction of buying power on a BUY
BUY_POWER_FRACTION = 0.95

ET = ZoneInfo("America/New_York")


def account_mode_banner(base_url: str, paper: bool) -> str:
    mode = "PAPER" if paper else "LIVE"
    return (
        f"!!! ACCOUNT MODE: {mode} !!!\n"
        f"Trading base URL: {base_url}\n"
        f"paper=True enforced on TradingClient: {paper}"
    )


def is_regular_market_hours(now: datetime | None = None) -> bool:
    """US equities regular session Mon-Fri 09:30-16:00 America/New_York."""
    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= minutes < (16 * 60)


def ensure_csv(path: Path, fieldnames: list[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()


def append_csv(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
    ensure_csv(path, fieldnames)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerow({k: row.get(k, "") for k in fieldnames})


SIGNAL_FIELDS = [
    "timestamp_utc",
    "symbol",
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

TRADE_FIELDS = [
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
]


def get_paper_trading_client() -> tuple[TradingClient, str]:
    api_key, secret_key = load_keys()
    # Force paper=True — never allow live client from this script.
    client = TradingClient(api_key, secret_key, paper=True)
    base_url = "https://paper-api.alpaca.markets"
    return client, base_url


def current_position_qty(client: TradingClient, symbol: str) -> float:
    try:
        pos = client.get_open_position(symbol)
        return float(pos.qty)
    except Exception:
        return 0.0


def execute_auto_trade(
    client: TradingClient,
    symbol: str,
    signal: str,
    close: float,
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
                "notes": f"already long {qty_held} shares",
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
                "notes": "insufficient buying power for 1 share",
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
            "notes": f"bought {shares} shares @ ~{close:.2f}",
            "side": "BUY",
            "qty": shares,
        }

    if signal == "SELL":
        if qty_held <= 0:
            return {
                "order_id": "",
                "order_status": "skipped",
                "notes": "no long position to sell",
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
            "notes": f"sold {shares} shares @ ~{close:.2f}",
            "side": "SELL",
            "qty": shares,
        }

    return {
        "order_id": "",
        "order_status": "skipped",
        "notes": f"unknown signal {signal}",
        "side": "",
        "qty": 0,
    }


def labels_by_name(payload: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["label"] for item in payload.get("indicators", [])}


def run_once(symbol: str, auto_trade: bool) -> dict[str, Any]:
    client, base_url = get_paper_trading_client()
    account = client.get_account()
    paper = True
    print("=" * 60)
    print(account_mode_banner(base_url, paper))
    print(f"Account status: {account.status} | equity=${float(account.equity):,.2f}")
    print(f"Symbol: {symbol} | auto_trade={auto_trade}")
    market_open = is_regular_market_hours()
    print(f"US regular market hours now: {market_open}")
    if auto_trade and not market_open:
        print("WARNING: --auto-trade set but market looks closed; order may be rejected.")
    print("=" * 60)

    df = fetch_daily_bars(symbol, trading_days=90)
    close = float(df["close"].iloc[-1])
    payload = generate_signal(df)
    print(format_signal_report(symbol, close, payload))

    order_id = ""
    order_status = "log_only"
    trade_meta: dict[str, Any] = {
        "side": "",
        "qty": 0,
        "notes": "auto_trade disabled - signal logged only",
    }

    if auto_trade:
        print("AUTO-TRADE ENABLED — submitting PAPER market order if applicable...")
        trade_meta = execute_auto_trade(client, symbol, payload["signal"], close)
        order_id = trade_meta.get("order_id", "")
        order_status = trade_meta.get("order_status", "")
        print(
            f"Order result: status={order_status} id={order_id or '-'} "
            f"notes={trade_meta.get('notes', '')}"
        )
        append_csv(
            TRADE_LOG,
            TRADE_FIELDS,
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "account_mode": "PAPER",
                "side": trade_meta.get("side", ""),
                "qty": trade_meta.get("qty", 0),
                "signal": payload["signal"],
                "score": payload["score"],
                "order_id": order_id,
                "order_status": order_status,
                "notes": trade_meta.get("notes", ""),
            },
        )
    else:
        print("Mode: LOG ONLY (pass --auto-trade to place paper orders)")

    labels = labels_by_name(payload)
    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
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
    print(f"Signal logged -> {SIGNAL_LOG}")
    return row


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live paper signal loop (localhost)")
    p.add_argument("--symbol", default="AAPL", help="Ticker to watch (default AAPL)")
    p.add_argument(
        "--interval",
        type=int,
        default=15,
        help="Minutes between runs when looping (default 15)",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit",
    )
    p.add_argument(
        "--auto-trade",
        action="store_true",
        help="OPT-IN: place Alpaca PAPER orders on BUY/SELL (default is log-only)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    symbol = args.symbol.upper()

    print("Phase 5 - Live paper signal bot (localhost)")
    print("Default is LOG ONLY. Orders require --auto-trade.")
    print()

    if args.once:
        run_once(symbol, auto_trade=args.auto_trade)
        print("Phase 5 single run complete.")
        return

    print(f"Looping every {args.interval} minute(s) on {symbol}. Ctrl+C to stop.")
    while True:
        try:
            run_once(symbol, auto_trade=args.auto_trade)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR during cycle: {exc}")
        print(f"Sleeping {args.interval} minute(s)...")
        time.sleep(max(args.interval, 1) * 60)


if __name__ == "__main__":
    main()

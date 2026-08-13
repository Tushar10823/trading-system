"""
Execute one paper trade from the current signal, with risk brackets on BUY.

Stop-loss / take-profit (chosen defaults):
  STOP_LOSS_PCT   = 3% below entry
  TAKE_PROFIT_PCT = 6% above entry

SELL closes any long. HOLD does nothing.
PAPER ONLY.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from market_data import fetch_daily_bars, load_keys
from signal_engine import generate_signal

SYMBOL = "AAPL"
STOP_LOSS_PCT = 0.03
TAKE_PROFIT_PCT = 0.06
OUTPUT = Path(__file__).resolve().parent / "output"
TRADE_LOG = OUTPUT / "paper_trades.csv"


def log_trade(row: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fields = [
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
    write_header = not TRADE_LOG.exists()
    with TRADE_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fields})


def main() -> None:
    api_key, secret = load_keys()
    client = TradingClient(api_key, secret, paper=True)
    account = client.get_account()

    print("=" * 60)
    print("ACCOUNT MODE: PAPER")
    print(f"Base URL: paper-api.alpaca.markets | equity=${float(account.equity):,.2f}")
    print(f"Risk defaults: stop-loss {STOP_LOSS_PCT:.0%} | take-profit {TAKE_PROFIT_PCT:.0%}")
    print("=" * 60)

    df = fetch_daily_bars(SYMBOL, trading_days=90)
    close = float(df["close"].iloc[-1])
    payload = generate_signal(df)
    signal = payload["signal"]
    score = payload["score"]
    print(f"Signal: {signal} | score={score} | ref_price={close:.4f}")
    print(f"Reason: {payload['reasoning']}")

    try:
        pos = client.get_open_position(SYMBOL)
        qty = float(pos.qty)
        avg = float(pos.avg_entry_price)
    except Exception:
        qty = 0.0
        avg = 0.0
    print(f"Open {SYMBOL}: qty={qty} avg_entry={avg:.4f}")

    if signal == "SELL":
        if qty <= 0:
            print("CALL: SELL but flat — no order submitted.")
            return
        shares = int(qty)
        print(f"CALL: SELL {shares} {SYMBOL} at market (~{close:.2f})")
        order = client.submit_order(
            MarketOrderRequest(
                symbol=SYMBOL,
                qty=shares,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
        )
        notes = f"closed long {shares} @~{close:.2f}; was avg {avg:.2f}"
        print(f"Order id={order.id} status={order.status}")
        log_trade(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": SYMBOL,
                "account_mode": "PAPER",
                "side": "SELL",
                "qty": shares,
                "signal": signal,
                "score": score,
                "order_id": str(order.id),
                "order_status": str(order.status),
                "notes": notes,
            }
        )
        print("Done. Position should be flat after fill.")
        return

    if signal == "BUY":
        if qty > 0:
            print(f"CALL: BUY but already long {qty} — no new order.")
            return
        # Small intentional size for a supervised paper trade (~$3k notional)
        budget = min(3000.0, float(account.buying_power) * 0.05)
        shares = max(int(budget // close), 1)
        entry = close
        take_profit = round(entry * (1 + TAKE_PROFIT_PCT), 2)
        stop_loss = round(entry * (1 - STOP_LOSS_PCT), 2)
        print(
            f"CALL: BUY {shares} {SYMBOL} bracket | entry~{entry:.2f} "
            f"| TP {take_profit:.2f} (+{TAKE_PROFIT_PCT:.0%}) "
            f"| SL {stop_loss:.2f} (-{STOP_LOSS_PCT:.0%})"
        )
        order = client.submit_order(
            MarketOrderRequest(
                symbol=SYMBOL,
                qty=shares,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=take_profit),
                stop_loss=StopLossRequest(stop_price=stop_loss),
            )
        )
        notes = f"bracket TP={take_profit} SL={stop_loss}"
        print(f"Order id={order.id} status={order.status}")
        log_trade(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": SYMBOL,
                "account_mode": "PAPER",
                "side": "BUY",
                "qty": shares,
                "signal": signal,
                "score": score,
                "order_id": str(order.id),
                "order_status": str(order.status),
                "notes": notes,
            }
        )
        return

    print("CALL: HOLD — no order.")


if __name__ == "__main__":
    main()

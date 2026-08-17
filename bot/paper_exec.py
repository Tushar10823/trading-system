"""
Alpaca PAPER execution for dashboard Buy/Sell calls.

TradingView paper cannot be driven from this bot (no official account link).
This module places the same 10-share paper trades on Alpaca instead.

Never import this from GitHub Actions (--once). Local --auto-trade only.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from market_data import load_keys

OUTPUT = Path(__file__).resolve().parent / "output"
STATE_FILE = OUTPUT / "paper_exec_state.json"
TRADE_LOG = OUTPUT / "dashboard_paper_trades.csv"


def paper_client() -> TradingClient:
    api_key, secret = load_keys()
    return TradingClient(api_key, secret, paper=True)


def load_last_actions() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {str(k).upper(): str(v) for k, v in (data.get("last_actions") or {}).items()}
    except json.JSONDecodeError:
        return {}


def save_last_actions(actions: dict[str, str]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"last_actions": actions, "saved_at": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8",
    )


def _qty(symbol: str, client: TradingClient) -> float:
    try:
        return float(client.get_open_position(symbol).qty)
    except Exception:
        return 0.0


def _cancel_open(client: TradingClient, symbol: str) -> None:
    try:
        orders = client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        )
        for order in orders:
            client.cancel_order_by_id(str(order.id))
    except Exception:
        pass


def _flatten(client: TradingClient, symbol: str) -> str:
    _cancel_open(client, symbol)
    qty = _qty(symbol, client)
    if qty == 0:
        return "flat"
    try:
        client.close_position(symbol)
        time.sleep(1.0)
        return f"closed {qty}"
    except Exception as exc:  # noqa: BLE001
        return f"flatten failed: {exc}"


def _bracket(side: OrderSide, qty: int, stop: Any, target: Any) -> dict[str, Any]:
    try:
        stop_px = float(stop)
        target_px = float(target)
    except (TypeError, ValueError):
        return {}
    return {
        "order_class": OrderClass.BRACKET,
        "take_profit": TakeProfitRequest(limit_price=round(target_px, 2)),
        "stop_loss": StopLossRequest(stop_price=round(stop_px, 2)),
    }


def execute_call(client: TradingClient, call: dict[str, Any], qty: int) -> dict[str, Any]:
    """Place one paper order for a BUY / SELL / EXIT call. Idempotent vs current position."""
    symbol = str(call.get("symbol", "")).upper()
    action = str(call.get("action", "")).upper()
    stop = call.get("stop")
    target = call.get("target")
    held = _qty(symbol, client)

    if action == "HOLD":
        return {"symbol": symbol, "ok": True, "notes": "HOLD — no order"}

    if action == "EXIT":
        notes = _flatten(client, symbol)
        return {"symbol": symbol, "ok": True, "action": "EXIT", "notes": notes}

    if action == "BUY":
        if held > 0:
            return {"symbol": symbol, "ok": True, "notes": f"already long {held} — skip"}
        if held < 0:
            _flatten(client, symbol)
        extra = _bracket(OrderSide.BUY, qty, stop, target)
        order = client.submit_order(
            MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
                **extra,
            )
        )
        return {
            "symbol": symbol,
            "ok": True,
            "action": "BUY",
            "qty": qty,
            "order_id": str(order.id),
            "status": str(order.status),
            "notes": f"PAPER BUY {qty} {symbol} SL {stop} TP {target}",
        }

    if action == "SELL":
        if held < 0:
            return {"symbol": symbol, "ok": True, "notes": f"already short {held} — skip"}
        if held > 0:
            _flatten(client, symbol)
        extra = _bracket(OrderSide.SELL, qty, stop, target)
        order = client.submit_order(
            MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                **extra,
            )
        )
        return {
            "symbol": symbol,
            "ok": True,
            "action": "SELL",
            "qty": qty,
            "order_id": str(order.id),
            "status": str(order.status),
            "notes": f"PAPER SELL/short {qty} {symbol} SL {stop} TP {target}",
        }

    return {"symbol": symbol, "ok": False, "notes": f"unhandled {action}"}


def arm_from_calls(calls: list[dict[str, Any]]) -> dict[str, str]:
    """Record current Buy/Sell without sending orders (avoids firing the whole board at once)."""
    last = load_last_actions()
    for c in calls:
        action = str(c.get("action", "")).upper()
        sym = str(c.get("symbol", "")).upper()
        if action in ("BUY", "SELL", "EXIT") and sym:
            last[sym] = action
    save_last_actions(last)
    return last


def execute_new_calls(calls: list[dict[str, Any]], qty: int) -> list[dict[str, Any]]:
    last = load_last_actions()
    client = paper_client()
    fills: list[dict[str, Any]] = []
    for c in calls:
        action = str(c.get("action", "")).upper()
        sym = str(c.get("symbol", "")).upper()
        if action not in ("BUY", "SELL", "EXIT") or not sym:
            continue
        if last.get(sym) == action:
            continue
        try:
            result = execute_call(client, c, qty)
        except Exception as exc:  # noqa: BLE001
            result = {"symbol": sym, "ok": False, "action": action, "notes": str(exc)}
        fills.append(result)
        if result.get("ok"):
            last[sym] = action
        print(f"  ALPACA PAPER {result.get('notes')}")
    save_last_actions(last)
    return fills

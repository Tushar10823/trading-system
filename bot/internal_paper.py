"""
Simple paper book on the dashboard (not Alpaca, not TradingView).

Fills at the bot's quoted price, 10 shares, with the same stop/target.
P&L is shown on the localhost page so you do not have to follow another broker UI.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

OUTPUT = Path(__file__).resolve().parent / "output"
BOOK_FILE = OUTPUT / "internal_paper.json"
IST = ZoneInfo("Asia/Kolkata")
STARTING_CASH = 100_000.0
DEFAULT_QTY = 10


def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")


def _empty() -> dict[str, Any]:
    return {
        "cash": STARTING_CASH,
        "starting_cash": STARTING_CASH,
        "realized_pnl": 0.0,
        "positions": [],
        "trades": [],
        "last_actions": {},
        "armed": False,
    }


def load_book() -> dict[str, Any]:
    if not BOOK_FILE.exists():
        return _empty()
    try:
        data = json.loads(BOOK_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty()
    data.setdefault("positions", [])
    data.setdefault("trades", [])
    data.setdefault("last_actions", {})
    data.setdefault("armed", False)
    data.setdefault("cash", STARTING_CASH)
    data.setdefault("starting_cash", STARTING_CASH)
    data.setdefault("realized_pnl", 0.0)
    return data


def save_book(book: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    BOOK_FILE.write_text(json.dumps(book, indent=2), encoding="utf-8")


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pos(book: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    for row in book["positions"]:
        if row["symbol"] == symbol:
            return row
    return None


def _close(book: dict[str, Any], pos: dict[str, Any], price: float, reason: str) -> str:
    qty = int(pos["qty"])
    entry = float(pos["entry"])
    if pos["side"] == "long":
        pnl = (price - entry) * qty
        book["cash"] += price * qty
    else:
        pnl = (entry - price) * qty
        book["cash"] -= price * qty  # buy to cover
    book["realized_pnl"] = round(float(book["realized_pnl"]) + pnl, 2)
    book["positions"] = [p for p in book["positions"] if p["symbol"] != pos["symbol"]]
    note = (
        f"{reason} {pos['side']} {qty} {pos['symbol']} @ {price:.2f} "
        f"P&L ${pnl:.2f} ({qty} sh)"
    )
    book["trades"].append(
        {
            "at": now_ist(),
            "symbol": pos["symbol"],
            "action": "CLOSE",
            "qty": qty,
            "price": round(price, 2),
            "pnl": round(pnl, 2),
            "notes": note,
        }
    )
    return note


def mark_to_market(book: dict[str, Any], prices: dict[str, float]) -> list[str]:
    notes: list[str] = []
    for pos in list(book["positions"]):
        px = prices.get(pos["symbol"])
        if px is None:
            continue
        pos["last"] = round(px, 2)
        stop = _to_float(pos.get("stop"))
        target = _to_float(pos.get("target"))
        if pos["side"] == "long":
            pos["pnl"] = round((px - float(pos["entry"])) * int(pos["qty"]), 2)
            hit_stop = stop is not None and px <= stop
            hit_tp = target is not None and px >= target
        else:
            pos["pnl"] = round((float(pos["entry"]) - px) * int(pos["qty"]), 2)
            hit_stop = stop is not None and px >= stop
            hit_tp = target is not None and px <= target
        if hit_stop:
            notes.append(_close(book, pos, px, "STOP"))
        elif hit_tp:
            notes.append(_close(book, pos, px, "TARGET"))
    return notes


def _open(
    book: dict[str, Any],
    symbol: str,
    side: str,
    price: float,
    qty: int,
    stop: Any,
    target: Any,
) -> str:
    notional = price * qty
    if side == "long":
        if book["cash"] < notional:
            return f"skip BUY {symbol}: not enough paper cash"
        book["cash"] -= notional
    else:
        book["cash"] += notional  # short proceeds
    book["positions"].append(
        {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry": round(price, 2),
            "stop": stop if stop not in (None, "-") else "-",
            "target": target if target not in (None, "-") else "-",
            "last": round(price, 2),
            "pnl": 0.0,
        }
    )
    label = "BUY" if side == "long" else "SELL"
    note = f"{label} {qty} {symbol} @ {price:.2f} SL {stop} TP {target}"
    book["trades"].append(
        {
            "at": now_ist(),
            "symbol": symbol,
            "action": label,
            "qty": qty,
            "price": round(price, 2),
            "pnl": 0.0,
            "notes": note,
        }
    )
    return note


def apply_new_calls(calls: list[dict[str, Any]], qty: int = DEFAULT_QTY) -> tuple[dict[str, Any], list[str]]:
    book = load_book()
    prices = {str(c["symbol"]).upper(): float(c["price"]) for c in calls if c.get("price") is not None}
    notes = mark_to_market(book, prices)

    if not book.get("armed"):
        for c in calls:
            action = str(c.get("action", "")).upper()
            sym = str(c.get("symbol", "")).upper()
            if action in ("BUY", "SELL", "EXIT") and sym:
                book["last_actions"][sym] = action
        book["armed"] = True
        save_book(book)
        return book, ["Paper book armed. Next new Buy/Sell auto-fills 10 shares on this page."]

    for c in calls:
        action = str(c.get("action", "")).upper()
        sym = str(c.get("symbol", "")).upper()
        if action not in ("BUY", "SELL", "EXIT") or not sym:
            continue
        if book["last_actions"].get(sym) == action:
            continue
        price = float(c.get("price") or c.get("entry") or 0)
        if price <= 0:
            continue
        pos = _pos(book, sym)
        if action == "EXIT":
            if pos and pos["side"] == "long":
                notes.append(_close(book, pos, price, "EXIT"))
            book["last_actions"][sym] = action
            continue
        if action == "BUY":
            if pos and pos["side"] == "short":
                notes.append(_close(book, pos, price, "COVER"))
            if not _pos(book, sym):
                notes.append(_open(book, sym, "long", price, qty, c.get("stop"), c.get("target")))
        if action == "SELL":
            if pos and pos["side"] == "long":
                notes.append(_close(book, pos, price, "SELL"))
            if not _pos(book, sym):
                notes.append(_open(book, sym, "short", price, qty, c.get("stop"), c.get("target")))
        book["last_actions"][sym] = action

    book["cash"] = round(float(book["cash"]), 2)
    book["equity"] = round(
        float(book["cash"]) + sum(float(p.get("pnl") or 0) for p in book["positions"]),
        2,
    )
    book["open_pnl"] = round(sum(float(p.get("pnl") or 0) for p in book["positions"]), 2)
    book["trades"] = book["trades"][-80:]
    save_book(book)
    return book, notes


def public_book() -> dict[str, Any]:
    book = load_book()
    open_pnl = sum(float(p.get("pnl") or 0) for p in book.get("positions") or [])
    cash = float(book.get("cash") or STARTING_CASH)
    start = float(book.get("starting_cash") or STARTING_CASH)
    return {
        "cash": round(cash, 2),
        "open_pnl": round(open_pnl, 2),
        "realized_pnl": round(float(book.get("realized_pnl") or 0), 2),
        "equity": round(cash + open_pnl, 2),
        "total_pnl": round(cash + open_pnl - start, 2),
        "positions": book.get("positions") or [],
        "trades": list(reversed(book.get("trades") or []))[:15],
        "armed": bool(book.get("armed")),
    }

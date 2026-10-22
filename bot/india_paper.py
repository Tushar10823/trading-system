"""
NSE paper book (not a broker). Large sleeve: 10 shares, Rs 10 lakh, 0.08%/side.
Small sleeve: Rs 1,000 fake, qty sized to budget, 0.20%/side (wider small-name band).

First scan arms only; next NEW/FLIP fills. No new entries after NSE cash close.
"""

from __future__ import annotations

import json
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from india_kpi import KILL_SWITCH_DD, evaluate_paper
from india_intraday_calls import SMALL_SET
from india_market_data import is_nse_market_hours

OUTPUT = Path(__file__).resolve().parent / "output"
BOOK_FILE = OUTPUT / "india_paper.json"
SMALL_BOOK_FILE = OUTPUT / "india_paper_small.json"
IST = ZoneInfo("Asia/Kolkata")
STARTING_CASH = 1_000_000.0  # Rs 10 lakh fake
SMALL_STARTING_CASH = 1_000.0
DEFAULT_QTY = 10
COST_PER_SIDE = 0.0008  # 0.08%
SMALL_COST_PER_SIDE = 0.002  # 0.20%
MAX_POSITIONS = 6
SMALL_MAX_POSITIONS = 5
HORIZON_MINUTES = 30
MAX_STOCK_PCT = 0.10
MAX_RISK_PCT = 0.01
SMALL_MAX_STOCK_PCT = 0.40
SMALL_MAX_RISK_PCT = 0.05
SMALL_NAME_CAP = 250.0  # target notional per small name so several fit in Rs 1k


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
        "paused": False,
        "currency": "INR",
        "sleeve": "large",
        "cost_per_side": COST_PER_SIDE,
        "max_positions": MAX_POSITIONS,
        "max_stock_pct": MAX_STOCK_PCT,
        "max_risk_pct": MAX_RISK_PCT,
    }


def _empty_small() -> dict[str, Any]:
    return {
        "cash": SMALL_STARTING_CASH,
        "starting_cash": SMALL_STARTING_CASH,
        "realized_pnl": 0.0,
        "positions": [],
        "trades": [],
        "last_actions": {},
        "armed": False,
        "paused": False,
        "currency": "INR",
        "sleeve": "small",
        "cost_per_side": SMALL_COST_PER_SIDE,
        "max_positions": SMALL_MAX_POSITIONS,
        "max_stock_pct": SMALL_MAX_STOCK_PCT,
        "max_risk_pct": SMALL_MAX_RISK_PCT,
    }


def _normalize(data: dict[str, Any], blank: dict[str, Any]) -> dict[str, Any]:
    for key, value in blank.items():
        data.setdefault(key, value)
    return data


def load_book(path: Path | None = None) -> dict[str, Any]:
    target = path or BOOK_FILE
    blank = _empty_small() if target == SMALL_BOOK_FILE else _empty()
    if not target.exists():
        return blank
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return blank
    return _normalize(data, blank)


def save_book(book: dict[str, Any], path: Path | None = None) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = path or (SMALL_BOOK_FILE if book.get("sleeve") == "small" else BOOK_FILE)
    target.write_text(json.dumps(book, indent=2), encoding="utf-8")


def _cost_rate(book: dict[str, Any]) -> float:
    try:
        return float(book.get("cost_per_side") or COST_PER_SIDE)
    except (TypeError, ValueError):
        return COST_PER_SIDE


def small_qty(price: float, cash: float) -> int:
    """Fit several 1-share-or-more lots inside the Rs 1,000 sleeve."""
    if price <= 0 or price > SMALL_STARTING_CASH:
        return 0
    cap = min(SMALL_NAME_CAP, max(cash, 0.0))
    qty = int(cap // price)
    if qty < 1 and price <= cash:
        qty = 1
    return qty


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


def _equity(book: dict[str, Any]) -> float:
    return float(book["cash"]) + sum(float(p.get("pnl") or 0) for p in book["positions"])


def _fill_cost(price: float, qty: int, rate: float = COST_PER_SIDE) -> float:
    return round(abs(price) * qty * rate, 2)


def _age_minutes(pos: dict[str, Any]) -> float:
    raw = pos.get("opened_at")
    if not raw:
        return float(HORIZON_MINUTES)
    try:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return (datetime.now(IST) - dt).total_seconds() / 60.0
    except ValueError:
        return 0.0


def _close(book: dict[str, Any], pos: dict[str, Any], price: float, reason: str) -> str:
    qty = int(pos["qty"])
    entry = float(pos["entry"])
    rate = _cost_rate(book)
    cost = _fill_cost(entry, qty, rate) + _fill_cost(price, qty, rate)
    if pos["side"] == "long":
        gross = (price - entry) * qty
        book["cash"] += price * qty
    else:
        gross = (entry - price) * qty
        book["cash"] -= price * qty
    book["cash"] -= cost
    pnl = round(gross - cost, 2)
    book["realized_pnl"] = round(float(book["realized_pnl"]) + pnl, 2)
    book["positions"] = [p for p in book["positions"] if p["symbol"] != pos["symbol"]]
    note = (
        f"{reason} {pos['side']} {qty} {pos['symbol']} @ {price:.2f} "
        f"P&L Rs {pnl:.2f} net ({qty} sh, costs Rs {cost:.2f})"
    )
    book["trades"].append(
        {
            "at": now_ist(),
            "symbol": pos["symbol"],
            "action": "CLOSE",
            "qty": qty,
            "price": round(price, 2),
            "pnl": pnl,
            "gross": round(gross, 2),
            "cost": cost,
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
        qty = int(pos["qty"])
        entry = float(pos["entry"])
        if pos["side"] == "long":
            pos["pnl"] = round((px - entry) * qty, 2)
            hit_stop = stop is not None and px <= stop
            hit_tp = target is not None and px >= target
        else:
            pos["pnl"] = round((entry - px) * qty, 2)
            hit_stop = stop is not None and px >= stop
            hit_tp = target is not None and px <= target
        if hit_stop:
            fill = stop if stop is not None else px
            notes.append(_close(book, pos, fill, "STOP"))
        elif hit_tp:
            fill = target if target is not None else px
            notes.append(_close(book, pos, fill, "TARGET"))
        elif _age_minutes(pos) >= HORIZON_MINUTES and float(pos.get("pnl") or 0) > 0:
            notes.append(_close(book, pos, px, "TIME"))
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
    if book.get("paused"):
        return f"skip {symbol}: kill switch paused new entries"
    max_pos = int(book.get("max_positions") or MAX_POSITIONS)
    if len(book["positions"]) >= max_pos:
        return f"skip {symbol}: max {max_pos} concurrent positions"
    equity = max(_equity(book), 1.0)
    notional = price * qty
    stock_cap = float(book.get("max_stock_pct") or MAX_STOCK_PCT)
    if notional / equity > stock_cap:
        return f"skip {symbol}: size {notional / equity:.1%} > {stock_cap:.0%} cap"
    stop_px = _to_float(stop)
    risk_cap = float(book.get("max_risk_pct") or MAX_RISK_PCT)
    if stop_px:
        risk = abs(price - stop_px) * qty / equity
        if risk > risk_cap:
            return f"skip {symbol}: stop risk {risk:.2%} > {risk_cap:.0%} of equity"
    cost = _fill_cost(price, qty, _cost_rate(book))
    if side == "long":
        if book["cash"] < notional + cost:
            return f"skip BUY {symbol}: not enough paper cash"
        book["cash"] -= notional + cost
    else:
        book["cash"] += notional - cost
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
            "opened_at": datetime.now(IST).isoformat(),
        }
    )
    label = "BUY" if side == "long" else "SELL"
    note = f"{label} {qty} {symbol} @ {price:.2f} SL {stop} TP {target} cost Rs {cost:.2f}"
    book["trades"].append(
        {
            "at": now_ist(),
            "symbol": symbol,
            "action": label,
            "qty": qty,
            "price": round(price, 2),
            "pnl": 0.0,
            "cost": cost,
            "notes": note,
        }
    )
    return note


def _apply_to_book(
    book: dict[str, Any],
    calls: list[dict[str, Any]],
    *,
    default_qty: int | None,
    arm_note: str,
    allow_new: bool,
) -> tuple[dict[str, Any], list[str]]:
    prices = {
        str(c["symbol"]).upper().removesuffix(".NS"): float(c["price"])
        for c in calls
        if c.get("price") is not None and c.get("symbol")
    }
    notes = mark_to_market(book, prices)
    start = float(book.get("starting_cash") or STARTING_CASH)
    eq = _equity(book)
    if start > 0 and (start - eq) / start >= KILL_SWITCH_DD:
        book["paused"] = True
        notes.append(f"Kill switch: drawdown >= {KILL_SWITCH_DD:.0%} — no new entries")

    if not book.get("armed"):
        if not allow_new:
            save_book(book)
            return book, ["Waiting for NSE 09:15 IST to arm this book (no after-hours fills)."]
        for c in calls:
            action = str(c.get("action", "")).upper()
            sym = str(c.get("symbol", "")).upper().removesuffix(".NS")
            if action in ("BUY", "SELL", "EXIT") and sym:
                book["last_actions"][sym] = action
        book["armed"] = True
        save_book(book)
        return book, [arm_note]

    for c in calls:
        action = str(c.get("action", "")).upper()
        sym = str(c.get("symbol", "")).upper().removesuffix(".NS")
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
        qty = default_qty if default_qty is not None else small_qty(price, float(book.get("cash") or 0))
        if qty <= 0:
            notes.append(f"skip {sym}: price Rs {price:.2f} does not fit the Rs 1,000 sleeve")
            continue
        if not allow_new:
            continue
        if action == "BUY":
            if pos and pos["side"] == "short":
                notes.append(_close(book, pos, price, "COVER"))
            if not _pos(book, sym):
                opened = _open(book, sym, "long", price, qty, c.get("stop"), c.get("target"))
                notes.append(opened)
                if opened.startswith("skip"):
                    continue
        if action == "SELL":
            if pos and pos["side"] == "long":
                notes.append(_close(book, pos, price, "SELL"))
            if not _pos(book, sym):
                opened = _open(book, sym, "short", price, qty, c.get("stop"), c.get("target"))
                notes.append(opened)
                if opened.startswith("skip"):
                    continue
        book["last_actions"][sym] = action

    book["cash"] = round(float(book["cash"]), 2)
    book["open_pnl"] = round(sum(float(p.get("pnl") or 0) for p in book["positions"]), 2)
    book["equity"] = round(float(book["cash"]) + float(book["open_pnl"]), 2)
    book["trades"] = book["trades"][-120:]
    save_book(book)
    return book, notes


def apply_new_calls(calls: list[dict[str, Any]], qty: int = DEFAULT_QTY) -> tuple[dict[str, Any], list[str]]:
    allow_new = is_nse_market_hours()
    large = [c for c in calls if str(c.get("symbol", "")).upper().removesuffix(".NS") not in SMALL_SET]
    small = [c for c in calls if str(c.get("symbol", "")).upper().removesuffix(".NS") in SMALL_SET]
    book, notes = _apply_to_book(
        load_book(BOOK_FILE),
        large,
        default_qty=qty,
        arm_note="Large book armed. Next new Buy/Sell fills 10 shares (net of 0.08%/side).",
        allow_new=allow_new,
    )
    _, small_notes = _apply_to_book(
        load_book(SMALL_BOOK_FILE),
        small,
        default_qty=None,
        arm_note="Rs 1,000 small-name book armed. Next new Buy/Sell sizes lots to the budget (0.20%/side).",
        allow_new=allow_new,
    )
    for line in small_notes:
        notes.append(f"SMALL {line}")
    if not allow_new:
        notes.append("NSE closed — marked open lots, no new paper entries until 09:15 IST.")
    return book, notes


def flatten_after_hours_leftovers() -> list[str]:
    """Close large-book lots opened after 15:30 IST so tomorrow has free slots."""
    book = load_book(BOOK_FILE)
    notes: list[str] = []
    for pos in list(book["positions"]):
        raw = pos.get("opened_at")
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
            local = dt.astimezone(IST)
        except ValueError:
            continue
        if local.time() < dtime(15, 30):
            continue
        px = float(pos.get("last") or pos.get("entry") or 0)
        if px <= 0:
            continue
        notes.append(_close(book, pos, px, "AFTER-HOURS FLAT"))
    if notes:
        book["cash"] = round(float(book["cash"]), 2)
        book["open_pnl"] = round(sum(float(p.get("pnl") or 0) for p in book["positions"]), 2)
        book["equity"] = round(float(book["cash"]) + float(book["open_pnl"]), 2)
        save_book(book, BOOK_FILE)
    return notes


def _refresh_one(path: Path, prices: dict[str, float]) -> None:
    book = load_book(path)
    px = dict(prices)
    held = [str(p.get("symbol", "")).upper() for p in book.get("positions") or [] if p.get("symbol")]
    if held:
        try:
            from india_market_data import fetch_latest_prices

            live = fetch_latest_prices(held)
            if live:
                px.update(live)
        except Exception:
            pass
    if not px:
        return
    mark_to_market(book, px)
    book["cash"] = round(float(book["cash"]), 2)
    book["open_pnl"] = round(sum(float(p.get("pnl") or 0) for p in book["positions"]), 2)
    book["equity"] = round(float(book["cash"]) + float(book["open_pnl"]), 2)
    book["marked_at"] = now_ist()
    start = float(book.get("starting_cash") or STARTING_CASH)
    if start > 0 and (start - float(book["equity"])) / start >= KILL_SWITCH_DD:
        book["paused"] = True
    save_book(book, path)


def refresh_mtm(prices: dict[str, float] | None = None) -> dict[str, Any]:
    px = {str(k).upper().removesuffix(".NS"): float(v) for k, v in (prices or {}).items()}
    _refresh_one(BOOK_FILE, px)
    _refresh_one(SMALL_BOOK_FILE, px)
    return public_book()


def _public(book: dict[str, Any]) -> dict[str, Any]:
    open_pnl = sum(float(p.get("pnl") or 0) for p in book.get("positions") or [])
    start = float(book.get("starting_cash") or STARTING_CASH)
    cash = float(book.get("cash") or start)
    kpi = evaluate_paper(book)
    if book.get("sleeve") == "small":
        kpi["cost_note"] = (
            "Rs 1,000 small-name sleeve · lots sized to budget · net of 0.20%/side. "
            "One-day confidence check only — not mixed with the 10-share large book."
        )
    return {
        "cash": round(cash, 2),
        "open_pnl": round(open_pnl, 2),
        "realized_pnl": round(float(book.get("realized_pnl") or 0), 2),
        "equity": round(cash + open_pnl, 2),
        "total_pnl": round(cash + open_pnl - start, 2),
        "starting_cash": round(start, 2),
        "currency": "INR",
        "sleeve": book.get("sleeve") or "large",
        "positions": book.get("positions") or [],
        "trades": list(reversed(book.get("trades") or []))[:20],
        "armed": bool(book.get("armed")),
        "paused": bool(book.get("paused")),
        "marked_at": book.get("marked_at") or "",
        "kpi": kpi,
    }


def public_book() -> dict[str, Any]:
    return _public(load_book(BOOK_FILE))


def public_small_book() -> dict[str, Any]:
    return _public(load_book(SMALL_BOOK_FILE))

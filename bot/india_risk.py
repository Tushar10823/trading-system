"""
NSE pre-trade risk check for the India paper book (india_paper.py).

Rupee version of the Trader pack's trader-risk. Every new BUY / SELL entry in
either sleeve is checked here before it fills; any reason blocks it. Exits,
stops, targets and covers are never blocked: they only lower risk.

What blocks an entry:
  ticker     not an NSE symbol (RELIANCE, M&M, BAJAJ-AUTO; .NS is stripped)
  blocked    on the BLOCKED list below
  size       order under the sleeve's minimum or over its maximum, in Rs
  edge       the target's gross profit doesn't beat the round-trip costs
             (buy + sell side) by MIN_EDGE_MULTIPLE, or there is no usable
             target, or the target / stop sit on the wrong side of the entry
  daily      more new entries today than the sleeve's daily limit

Tune the limits at the top of this file.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Per-sleeve limits in rupees. "large" = Rs 10 lakh book, "small" = Rs 1,000 book.
LIMITS: dict[str, dict[str, float]] = {
    "large": {"max_order_inr": 100_000, "min_order_inr": 1_000, "max_entries_per_day": 20},
    "small": {"max_order_inr": 400, "min_order_inr": 10, "max_entries_per_day": 10},
}
# Target profit must be at least this many times the round-trip costs (1.0 = just cover them).
MIN_EDGE_MULTIPLE = 1.0
BLOCKED: set[str] = set()

NSE_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}$")


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def entries_today(book: dict[str, Any], today: str | None = None) -> int:
    """New BUY / SELL entries the book opened today (trade "at" is 'YYYY-MM-DD HH:MM IST')."""
    day = today or datetime.now(IST).strftime("%Y-%m-%d")
    return sum(
        1
        for t in book.get("trades", [])
        if t.get("action") in ("BUY", "SELL") and str(t.get("at", "")).startswith(day)
    )


def check_entry(
    book: dict[str, Any],
    symbol: str,
    side: str,
    price: float,
    qty: int,
    stop: Any,
    target: Any,
    cost_rate: float,
    today: str | None = None,
) -> list[str]:
    """Reasons to block this entry; an empty list means PASS. side is "long" or "short"."""
    sleeve = "small" if book.get("sleeve") == "small" else "large"
    lim = LIMITS[sleeve]
    sym = symbol.upper().removesuffix(".NS")
    reasons: list[str] = []

    if not NSE_SYMBOL.match(sym):
        reasons.append(f"ticker: {symbol!r} is not an NSE symbol")
    if sym in BLOCKED:
        reasons.append(f"blocked: {sym} is on the blocked list")

    notional = price * qty
    if notional > lim["max_order_inr"]:
        reasons.append(f"size: Rs {notional:,.0f} is over the Rs {lim['max_order_inr']:,.0f} max order")
    if notional < lim["min_order_inr"]:
        reasons.append(f"size: Rs {notional:,.0f} is under the Rs {lim['min_order_inr']:,.0f} minimum")

    target_px = _num(target)
    stop_px = _num(stop)
    if target_px is None:
        reasons.append("edge: no target price, so the trade can't be checked against costs")
    else:
        move = target_px - price if side == "long" else price - target_px
        if move <= 0:
            reasons.append(f"edge: target {target_px:.2f} is on the wrong side of entry {price:.2f}")
        else:
            gross = move * qty
            round_trip = (price + target_px) * qty * cost_rate
            if gross < round_trip * MIN_EDGE_MULTIPLE:
                reasons.append(
                    f"edge: target makes Rs {gross:.2f} but round-trip costs are Rs {round_trip:.2f}"
                )
    if stop_px is not None:
        wrong = stop_px >= price if side == "long" else stop_px <= price
        if wrong:
            reasons.append(f"edge: stop {stop_px:.2f} is on the wrong side of entry {price:.2f}")

    done = entries_today(book, today)
    if done >= lim["max_entries_per_day"]:
        reasons.append(f"daily: {done} entries today, limit is {int(lim['max_entries_per_day'])}")

    return reasons

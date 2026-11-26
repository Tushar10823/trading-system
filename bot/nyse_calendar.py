"""
NYSE trading calendar: regular hours, holidays and 1:00 p.m. early closes.

One place for "is the US market open?" so the board, the paper book and the
Alpaca auto-trade paths all agree. Dates are NYSE's published schedule for
2026-2027 (same list as the Trader pack's trader-alerts). Add the next year's
dates before it starts; outside the listed years only weekends are closed and
a warning is printed once.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)
CALENDAR_YEARS = (2026, 2027)

HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed)",
}
EARLY_CLOSES = {
    "2026-11-27": "day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
    "2027-11-26": "day after Thanksgiving",
}

_warned: set[int] = set()


def _now(now: datetime | None) -> datetime:
    now = now or datetime.now(ET)
    return now.replace(tzinfo=ET) if now.tzinfo is None else now.astimezone(ET)


def session(d: date) -> tuple[time, time] | None:
    """(open, close) in New York time for that day, or None when NYSE is closed."""
    if d.weekday() >= 5 or d.isoformat() in HOLIDAYS:
        return None
    if d.year not in CALENDAR_YEARS and d.year not in _warned:
        _warned.add(d.year)
        print(f"WARNING: nyse_calendar.py has no holidays for {d.year}; add them (only weekends are closed now)")
    return OPEN, (EARLY_CLOSE if d.isoformat() in EARLY_CLOSES else CLOSE)


def is_open(now: datetime | None = None) -> bool:
    now = _now(now)
    hours = session(now.date())
    return bool(hours) and hours[0] <= now.time() < hours[1]


def minutes_to_close(now: datetime | None = None) -> int:
    """Minutes until today's close (early closes included); 0 when closed."""
    now = _now(now)
    hours = session(now.date())
    if not hours or not is_open(now):
        return 0
    close = now.replace(hour=hours[1].hour, minute=hours[1].minute, second=0, microsecond=0)
    return int((close - now).total_seconds() // 60)


def closed_reason(now: datetime | None = None) -> str:
    """Why the market is closed right now ("" when open)."""
    now = _now(now)
    d = now.date()
    if is_open(now):
        return ""
    if d.weekday() >= 5:
        return "weekend"
    if d.isoformat() in HOLIDAYS:
        return f"NYSE holiday: {HOLIDAYS[d.isoformat()]}"
    hours = session(d)
    if hours and now.time() >= hours[1] and d.isoformat() in EARLY_CLOSES:
        return f"early close at 1:00 p.m. ({EARLY_CLOSES[d.isoformat()]})"
    return "outside regular hours (9:30 a.m. to 4:00 p.m. New York)"

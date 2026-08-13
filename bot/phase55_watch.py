"""
Phase 5.5 watcher — re-run the news+vol scan on a loop.

Stays quiet while previous BUY/SELL calls are still valid.
Prints an update only when:
  - a call flips (BUY<->SELL, or BUY/SELL -> HOLD)
  - price hits stop (plan went wrong)
  - price hits target (plan completed — drop the old call)
  - a new BUY/SELL appears that we did not have before

Usage:
  python phase55_watch.py
  python phase55_watch.py --top 5 --interval 5
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from phase55_news_scanner import collect_scan

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
STATE_FILE = OUTPUT_DIR / "phase55_watch_state.json"
IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")


ACTIONABLE = ("BUY", "SELL", "EXIT", "SHORT")


def snapshot_actionable(calls: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for c in calls:
        if c.get("action") not in ACTIONABLE:
            continue
        out[c["symbol"]] = {
            "action": c["action"],
            "price": c["price"],
            "entry": c["entry"],
            "stop": c["stop"],
            "target": c["target"],
            "wait_min": c.get("wait_min", 30),
            "wait_until": c.get("wait_until", "-"),
            "wait_until_iso": c.get("wait_until_iso", ""),
            "confidence": c.get("confidence", ""),
        }
    return out


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"calls": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"calls": {}}


def save_state(calls: dict[str, dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"saved_at": now_ist(), "calls": calls}, indent=2),
        encoding="utf-8",
    )


def evaluate_changes(
    previous: dict[str, dict[str, Any]],
    current_calls: list[dict[str, Any]],
) -> list[str]:
    current_map = {c["symbol"]: c for c in current_calls}
    events: list[str] = []

    for symbol, prev in previous.items():
        cur = current_map.get(symbol)
        price = to_float(cur["price"]) if cur else to_float(prev.get("price"))
        stop = to_float(prev.get("stop"))
        target = to_float(prev.get("target"))
        action = prev.get("action")

        if price is not None and stop is not None and target is not None:
            if action == "BUY" and price <= stop:
                events.append(
                    f"WRONG/STOP  {symbol} BUY invalidated — price {price} hit stop {stop}"
                )
                continue
            if action == "BUY" and price >= target:
                events.append(
                    f"TARGET HIT  {symbol} BUY worked — price {price} reached target {target}"
                )
                continue
            if action == "SHORT" and price >= stop:
                events.append(
                    f"WRONG/STOP  {symbol} SHORT invalidated — price {price} hit stop {stop}"
                )
                continue
            if action == "SHORT" and price <= target:
                events.append(
                    f"TARGET HIT  {symbol} SHORT worked — price {price} reached target {target}"
                )
                continue
            if action == "SELL" and price >= stop:
                events.append(
                    f"WRONG/STOP  {symbol} SELL invalidated — price {price} hit stop {stop}"
                )
                continue
            if action == "SELL" and price <= target:
                events.append(
                    f"TARGET HIT  {symbol} SELL worked — price {price} reached target {target}"
                )
                continue

        new_action = cur["action"] if cur else "HOLD"
        if new_action != action:
            still_waiting = False
            iso = prev.get("wait_until_iso") or ""
            if iso:
                try:
                    until = datetime.fromisoformat(iso)
                    still_waiting = datetime.now(until.tzinfo) < until
                except ValueError:
                    still_waiting = False
            if still_waiting and new_action != "EXIT":
                continue
            events.append(
                f"FLIP        {symbol} {action} -> {new_action} @ {price} "
                f"(was {action} entry {prev.get('entry')})"
            )

    prev_symbols = set(previous)
    for c in current_calls:
        if c["action"] in ACTIONABLE and c["symbol"] not in prev_symbols:
            events.append(
                f"NEW         {c['action']} {c['symbol']} @ {c['entry']} "
                f"| stop {c['stop']} | target {c['target']}"
            )

    return events


def print_idle(current: dict[str, dict[str, Any]]) -> None:
    if not current:
        print(f"[{now_ist()}] IDLE — no actionable BUY/SELL; waiting on market")
        return
    bits = [
        f"{sym} {row['action']}@{row['entry']} SL {row['stop']} TP {row['target']} wait until {row.get('wait_until', '-')}"
        for sym, row in current.items()
    ]
    print(f"[{now_ist()}] IDLE — calls still valid: " + "; ".join(bits))


def run_cycle(top: int, first: bool) -> dict[str, dict[str, Any]]:
    verbose = first
    if first:
        print("=" * 72)
        print("PHASE 5.5 WATCHER — updates only when a call looks wrong")
        print(f"Started {now_ist()} | paper research | Ctrl+C to stop")
        print("=" * 72)
    result = collect_scan(top_n=top, verbose=verbose)
    current = snapshot_actionable(result["calls"])
    previous = load_state().get("calls") or {}

    if first:
        save_state(current)
        if current:
            print("Watching these calls. Will stay idle until one flips or hits stop/target.")
        else:
            print("No BUY/SELL yet. Will stay idle until one appears.")
        return current

    events = evaluate_changes(previous, result["calls"])
    if not events:
        print_idle(current)
        save_state(current)
        return current

    print()
    print("!" * 72)
    print(f"UPDATE {now_ist()} — previous call changed")
    print("!" * 72)
    for line in events:
        print(f"  {line}")
    print()
    from phase55_news_scanner import print_calls, log_calls

    log_calls(result["calls"])
    print_calls(result["calls"])
    save_state(current)
    return current


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Phase 5.5 calls for reversals")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Minutes between scans (default 30)",
    )
    args = parser.parse_args()
    interval = max(1, args.interval)

    first = True
    while True:
        try:
            run_cycle(args.top, first=first)
        except Exception as exc:  # noqa: BLE001
            print(f"[{now_ist()}] ERROR during scan: {exc}")
        first = False
        print(f"  next check in {interval} min...")
        time.sleep(interval * 60)


if __name__ == "__main__":
    main()

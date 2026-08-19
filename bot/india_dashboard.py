"""
NSE paper-call dashboard (Yahoo Finance .NS data).

  python india_dashboard.py
  python india_dashboard.py --port 8788 --interval 30
  python india_dashboard.py --once

Open http://localhost:8788  (or /india/ on GitHub Pages)
LOG ONLY. Does not place orders.
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from india_intraday_calls import (
    DEFAULT_WATCHLIST,
    analyze_symbol,
    log_calls,
)
from india_market_data import is_nse_market_hours, minutes_to_nse_close
from phase55_watch import ACTIONABLE, evaluate_changes, snapshot_actionable

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
HTML_FILE = ROOT / "static" / "india_dashboard.html"
STATE_FILE = OUTPUT_DIR / "india_dashboard_state.json"
PREV_STATE_FILE = OUTPUT_DIR / "india_prev_state.json"
SITE_DIR = ROOT / "site" / "india"
IST = ZoneInfo("Asia/Kolkata")

LOCK = threading.Lock()
SCAN_LOCK = threading.Lock()
STATE: dict[str, Any] = {
    "status": "starting",
    "market": "NSE",
    "scanned_at": "",
    "next_scan_at": "",
    "interval_min": 30,
    "watchlist": list(DEFAULT_WATCHLIST),
    "calls": [],
    "events": [],
    "error": "",
    "nse_open": False,
    "minutes_to_close": 0,
}
PREVIOUS_ACTIONABLE: dict[str, dict[str, Any]] = {}
WAKE = threading.Event()


def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")


def restore_from_prev() -> None:
    global PREVIOUS_ACTIONABLE
    if not PREV_STATE_FILE.exists():
        return
    try:
        data = json.loads(PREV_STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    prev_calls: dict[str, dict[str, Any]] = {}
    for c in data.get("calls") or []:
        if c.get("action") in ACTIONABLE and c.get("symbol"):
            sym = str(c["symbol"]).upper()
            prev_calls[sym] = {
                "action": c.get("action"),
                "price": c.get("price"),
                "entry": c.get("entry"),
                "stop": c.get("stop"),
                "target": c.get("target"),
                "wait_min": c.get("wait_min", 30),
                "wait_until": c.get("wait_until", "-"),
                "wait_until_iso": c.get("wait_until_iso", ""),
                "confidence": c.get("confidence", ""),
            }
    PREVIOUS_ACTIONABLE = prev_calls
    with LOCK:
        STATE["events"] = list(data.get("events") or [])[-80:]
        STATE["watchlist"] = list(data.get("watchlist") or DEFAULT_WATCHLIST)


def slim_call(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": c.get("symbol"),
        "price": c.get("price"),
        "action": c.get("action"),
        "entry": c.get("entry"),
        "stop": c.get("stop"),
        "target": c.get("target"),
        "wait_min": c.get("wait_min", 0),
        "wait_until": c.get("wait_until", "-"),
        "signal_30m": c.get("signal_30m"),
        "signal_5m": c.get("signal_5m"),
        "confidence": c.get("confidence", ""),
        "atr_pct": c.get("atr_pct"),
        "target_pct": c.get("target_pct"),
        "target_inr": c.get("target_inr"),
        "target_on_10": c.get("target_on_10"),
    }


def public_state() -> dict[str, Any]:
    with LOCK:
        out = dict(STATE)
    nxt = out.get("next_scan_at") or ""
    if nxt:
        try:
            until = datetime.fromisoformat(nxt)
            secs = max(0, int((until - datetime.now(until.tzinfo)).total_seconds()))
            out["next_scan_in"] = f"{secs // 60}m {secs % 60}s"
        except ValueError:
            out["next_scan_in"] = nxt
    return out


def persist_state() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK:
        payload = dict(STATE)
    STATE_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def export_site(site_dir: Path) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    html = HTML_FILE.read_text(encoding="utf-8")
    (site_dir / "index.html").write_text(html, encoding="utf-8")
    (site_dir / "state.json").write_text(
        json.dumps(public_state(), indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Wrote NSE static site -> {site_dir}")


def run_scan(symbols: list[str], interval_min: int) -> None:
    global PREVIOUS_ACTIONABLE
    if not SCAN_LOCK.acquire(blocking=False):
        return
    try:
        with LOCK:
            STATE["status"] = "scanning"
            STATE["error"] = ""
        persist_state()

        calls: list[dict[str, Any]] = []
        for sym in symbols:
            try:
                calls.append(analyze_symbol(sym))
                print(f"  scanned {sym}")
            except Exception as exc:  # noqa: BLE001
                print(f"  skip {sym}: {exc}")

        if calls:
            log_calls(calls)

        change_lines = evaluate_changes(PREVIOUS_ACTIONABLE, calls)
        PREVIOUS_ACTIONABLE = snapshot_actionable(calls)

        events: list[dict[str, str]] = []
        with LOCK:
            events = list(STATE.get("events") or [])
        stamp = now_ist()
        for line in change_lines:
            events.append({"at": stamp, "text": line})
        events = events[-80:]

        next_at = datetime.now(IST) + timedelta(minutes=interval_min)
        with LOCK:
            STATE.update(
                {
                    "status": "idle",
                    "scanned_at": stamp,
                    "next_scan_at": next_at.isoformat(),
                    "interval_min": interval_min,
                    "watchlist": symbols,
                    "calls": [slim_call(c) for c in calls],
                    "events": events,
                    "nse_open": is_nse_market_hours(),
                    "minutes_to_close": minutes_to_nse_close() if is_nse_market_hours() else 0,
                    "error": "",
                }
            )
        persist_state()
        print(f"[{stamp}] NSE scan done · {len(calls)} names")
        for c in calls:
            if c.get("action") in ("BUY", "SELL", "EXIT"):
                print(
                    f"  {c['action']:4} {c['symbol']:12} @ ₹{c['entry']} "
                    f"SL ₹{c['stop']} TP ₹{c['target']} wait {c.get('wait_until')}"
                )
    except Exception as exc:  # noqa: BLE001
        with LOCK:
            STATE["status"] = "error"
            STATE["error"] = str(exc)
        persist_state()
        print(f"[{now_ist()}] ERROR {exc}")
    finally:
        SCAN_LOCK.release()


def loop(symbols: list[str], interval_min: int) -> None:
    while True:
        run_scan(symbols, interval_min)
        if not WAKE.is_set():
            WAKE.wait(timeout=max(1, interval_min) * 60)
        WAKE.clear()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        if "/api/" not in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/state":
            body = json.dumps(public_state(), default=str).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if self.path in ("/", "/index.html"):
            self._send(200, HTML_FILE.read_bytes(), "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/scan":
            WAKE.set()
            self._send(200, b'{"ok":true}', "application/json")
            return
        self._send(404, b"not found", "text/plain")


def _lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="NSE paper-call dashboard")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--interval", type=int, default=30, help="Minutes between scans")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan, write bot/site/india for GitHub Pages, then exit",
    )
    parser.add_argument("--site-dir", default=str(SITE_DIR))
    args = parser.parse_args()

    symbols = list(DEFAULT_WATCHLIST)
    restore_from_prev()
    with LOCK:
        STATE["interval_min"] = max(1, args.interval)
        STATE["watchlist"] = symbols

    if args.once:
        run_scan(symbols, max(1, args.interval))
        export_site(Path(args.site_dir))
        return

    worker = threading.Thread(
        target=loop, args=(symbols, max(1, args.interval)), daemon=True
    )
    worker.start()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"NSE dashboard on this PC:  http://127.0.0.1:{args.port}")
    lan = _lan_ip()
    if lan:
        print(f"On your phone (same Wi-Fi): http://{lan}:{args.port}")
    print(f"Scan every {args.interval} min · {len(symbols)} Nifty liquid names")
    print("Keep this PC awake. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

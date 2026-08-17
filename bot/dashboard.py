"""
Localhost dashboard for Phase 5.5 paper calls.

Scans on a 30-minute interval, auto-adds any ticker that prints BUY or SELL,
and keeps those names on the board for later scans.

  python dashboard.py
  python dashboard.py --port 8787 --interval 30 --top 10

Open http://localhost:8787
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

from phase55_news_scanner import ALWAYS_INCLUDE, collect_scan
from phase55_watch import ACTIONABLE, evaluate_changes, snapshot_actionable
from intraday_calls import is_regular_market_hours, minutes_to_close, log_calls

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
HTML_FILE = ROOT / "static" / "dashboard.html"
WATCHLIST_FILE = OUTPUT_DIR / "dynamic_watchlist.json"
STATE_FILE = OUTPUT_DIR / "dashboard_state.json"
PREV_STATE_FILE = OUTPUT_DIR / "prev_state.json"
SITE_DIR = ROOT / "site"
IST = ZoneInfo("Asia/Kolkata")

LOCK = threading.Lock()
SCAN_LOCK = threading.Lock()
STATE: dict[str, Any] = {
    "status": "starting",
    "scanned_at": "",
    "next_scan_at": "",
    "interval_min": 30,
    "watchlist": list(ALWAYS_INCLUDE),
    "added": {},
    "calls": [],
    "events": [],
    "error": "",
    "market_open": False,
    "minutes_to_close": 0,
    "auto_trade": False,
    "fills": [],
}
PREVIOUS_ACTIONABLE: dict[str, dict[str, Any]] = {}
WAKE = threading.Event()


def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")


def load_watchlist() -> tuple[list[str], dict[str, Any]]:
    if not WATCHLIST_FILE.exists():
        return list(ALWAYS_INCLUDE), {}
    try:
        data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return list(ALWAYS_INCLUDE), {}
    symbols = [str(s).upper() for s in data.get("symbols") or []]
    for s in ALWAYS_INCLUDE:
        if s not in symbols:
            symbols.insert(0, s)
    return symbols, data.get("added") or {}


def save_watchlist(symbols: list[str], added: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WATCHLIST_FILE.write_text(
        json.dumps({"symbols": symbols, "added": added, "saved_at": now_ist()}, indent=2),
        encoding="utf-8",
    )


def restore_from_prev() -> None:
    """Reload watchlist/events from the last published board (used in GitHub Actions)."""
    global PREVIOUS_ACTIONABLE
    if not PREV_STATE_FILE.exists():
        return
    try:
        data = json.loads(PREV_STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    symbols = [str(s).upper() for s in data.get("watchlist") or []]
    added = data.get("added") or {}
    if symbols:
        save_watchlist(symbols, added)
    prev_calls: dict[str, dict[str, Any]] = {}
    for c in data.get("calls") or []:
        if c.get("action") in ACTIONABLE and c.get("symbol"):
            prev_calls[str(c["symbol"]).upper()] = {
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
        STATE["watchlist"] = symbols or list(ALWAYS_INCLUDE)
        STATE["added"] = added


def export_site(site_dir: Path) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    html = HTML_FILE.read_text(encoding="utf-8")
    (site_dir / "index.html").write_text(html, encoding="utf-8")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    (site_dir / "state.json").write_text(
        json.dumps(public_state(), indent=2, default=str),
        encoding="utf-8",
    )
    book_src = OUTPUT_DIR / "internal_paper.json"
    if book_src.exists():
        (site_dir / "paper.json").write_text(book_src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Wrote static site -> {site_dir}")


def persist_state() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK:
        payload = dict(STATE)
    STATE_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


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


def slim_call(c: dict[str, Any], watchlist: list[str], added: dict[str, Any]) -> dict[str, Any]:
    sym = c.get("symbol")
    return {
        "symbol": sym,
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
        "headline": c.get("headline", ""),
        "auto_added": bool(sym in added) or (sym in watchlist and sym not in ALWAYS_INCLUDE),
    }


def run_scan(top_n: int, interval_min: int) -> None:
    global PREVIOUS_ACTIONABLE
    if not SCAN_LOCK.acquire(blocking=False):
        return
    try:
        with LOCK:
            STATE["status"] = "scanning"
            STATE["error"] = ""
        persist_state()

        symbols, added = load_watchlist()
        result = collect_scan(top_n=top_n, verbose=False, extra_symbols=symbols)
        calls = result.get("calls") or []
        if calls:
            log_calls(calls)

        new_adds: list[str] = []
        for c in calls:
            action = c.get("action")
            sym = str(c.get("symbol", "")).upper()
            if action in ("BUY", "SELL") and sym:
                if sym not in symbols:
                    symbols.append(sym)
                    new_adds.append(sym)
                added[sym] = {
                    "reason": action,
                    "at": now_ist(),
                    "entry": c.get("entry"),
                    "stop": c.get("stop"),
                    "target": c.get("target"),
                    "wait_until": c.get("wait_until"),
                }
        save_watchlist(symbols, added)

        current = snapshot_actionable(calls)
        change_lines = evaluate_changes(PREVIOUS_ACTIONABLE, calls)
        PREVIOUS_ACTIONABLE = current

        events: list[dict[str, str]] = []
        with LOCK:
            events = list(STATE.get("events") or [])
        stamp = now_ist()
        for line in change_lines:
            events.append({"at": stamp, "text": line})
        for sym in new_adds:
            events.append({"at": stamp, "text": f"ADDED {sym} to board (Buy/Sell required)"})

        fills: list[dict[str, Any]] = []
        paper: dict[str, Any] = {}
        if CFG.get("paper_book") and not CFG.get("once"):
            from internal_paper import apply_new_calls, public_book

            _book, paper_notes = apply_new_calls(calls, int(CFG.get("qty", 10)))
            for line in paper_notes:
                events.append({"at": stamp, "text": f"PAPER {line}"})
                print(f"  PAPER {line}")
            paper = public_book()
        if CFG.get("auto_trade") and not CFG.get("once"):
            from paper_exec import arm_from_calls, execute_new_calls, load_last_actions

            if not load_last_actions():
                arm_from_calls(calls)
                events.append(
                    {
                        "at": stamp,
                        "text": "ALPACA PAPER auto-trade armed — next NEW/FLIP Buy/Sell sends 10-share paper orders (not TradingView)",
                    }
                )
                print("  auto-trade armed (no basket of orders on this scan)")
            else:
                fills = execute_new_calls(calls, int(CFG.get("qty", 10)))
                for fill in fills:
                    events.append({"at": stamp, "text": f"ALPACA {fill.get('notes')}"})

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
                    "added": added,
                    "calls": [slim_call(c, symbols, added) for c in calls],
                    "events": events,
                    "market_open": is_regular_market_hours(),
                    "minutes_to_close": minutes_to_close() if is_regular_market_hours() else 0,
                    "error": "",
                    "auto_trade": bool(CFG.get("auto_trade")),
                    "paper_book": bool(CFG.get("paper_book")),
                    "paper": paper,
                    "fills": fills[-20:],
                }
            )
        persist_state()
        print(f"[{stamp}] scan done · {len(calls)} names · watchlist {symbols}")
        for c in calls:
            if c.get("action") in ("BUY", "SELL", "EXIT"):
                print(
                    f"  {c['action']:4} {c['symbol']:5} @ {c['entry']} "
                    f"SL {c['stop']} TP {c['target']} wait {c.get('wait_until')}"
                )
    except Exception as exc:  # noqa: BLE001
        with LOCK:
            STATE["status"] = "error"
            STATE["error"] = str(exc)
        persist_state()
        print(f"[{now_ist()}] ERROR {exc}")
    finally:
        SCAN_LOCK.release()


def loop(top_n: int, interval_min: int) -> None:
    while True:
        run_scan(top_n, interval_min)
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
            html = HTML_FILE.read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/scan":
            WAKE.set()
            self._send(200, b'{"ok":true}', "application/json")
            return
        self._send(404, b"not found", "text/plain")


CFG: dict[str, Any] = {
    "top": 10,
    "interval": 30,
    "auto_trade": False,
    "paper_book": True,
    "qty": 10,
    "once": False,
}


def _lan_ip() -> str:
    """Best-effort Wi-Fi/LAN IPv4 so a phone on the same network can open the board."""
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
    parser = argparse.ArgumentParser(description="Localhost paper-call dashboard")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address (0.0.0.0 lets a phone on the same Wi-Fi open the board)",
    )
    parser.add_argument("--interval", type=int, default=30, help="Minutes between scans")
    parser.add_argument("--top", type=int, default=10, help="Heat names to scan besides watchlist")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan, write bot/site for GitHub Pages, then exit",
    )
    parser.add_argument("--site-dir", default=str(SITE_DIR))
    parser.add_argument(
        "--auto-trade",
        action="store_true",
        help="Place Alpaca PAPER orders (10 shares) on new Buy/Sell. Not TradingView.",
    )
    parser.add_argument("--qty", type=int, default=10, help="Paper shares per new Buy/Sell")
    args = parser.parse_args()
    CFG["top"] = max(1, args.top)
    CFG["interval"] = max(1, args.interval)
    CFG["auto_trade"] = bool(args.auto_trade) and not args.once
    CFG["paper_book"] = True
    CFG["qty"] = max(1, args.qty)
    CFG["once"] = bool(args.once)

    restore_from_prev()
    with LOCK:
        STATE["interval_min"] = CFG["interval"]
        STATE["watchlist"], STATE["added"] = load_watchlist()

    if args.once:
        run_scan(CFG["top"], CFG["interval"])
        export_site(Path(args.site_dir))
        return

    worker = threading.Thread(target=loop, args=(CFG["top"], CFG["interval"]), daemon=True)
    worker.start()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Dashboard on this PC:  http://127.0.0.1:{args.port}")
    lan = _lan_ip()
    if lan:
        print(f"On your phone (same Wi-Fi): http://{lan}:{args.port}")
    print(f"Scan every {CFG['interval']} min · top {CFG['top']} + auto-added Buy/Sell names")
    if CFG["paper_book"]:
        print(f"Paper book ON this page · {CFG['qty']} shares · starting $100,000 fake cash")
        print("Not TradingView and not Alpaca. Watch positions on http://127.0.0.1:8787")
    if CFG["auto_trade"]:
        print("Also sending Alpaca paper orders (optional).")
    print("Keep this PC awake. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

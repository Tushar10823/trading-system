"""
One app for everything: US board, India board and the Trader tools on one page.

  python app.py                      # http://127.0.0.1:8790
  python app.py --us-auto-trade      # also send Alpaca PAPER orders (through trader-risk)
  python app.py --no-us              # India board + tools only

Runs the US scan loop (dashboard.py) and the NSE scan loop (india_dashboard.py)
in one process and serves their existing pages under /us/ and /in/, plus the
Trader Desk (11 Trader skill tools) under /tools/. The boards can be opened
from a phone on the same Wi-Fi; the tools only answer on this PC.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import dashboard as us
import india_dashboard as india
from trader_desk.server import CONFIG_DEFAULTS, TOOLS, App, find_action

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
APP_HTML = ROOT / "static" / "app.html"
DESK_HTML = ROOT / "trader_desk" / "index.html"
LOOPBACK = {"127.0.0.1", "::1"}

DESK = App(str(Path.home() / ".claude" / "skills"), str(REPO_ROOT))
ENABLED = {"us": True, "in": True}


def relative_api(html: bytes) -> bytes:
    """Point a page's "/api/..." calls at its own prefix (/us/api/..., /in/api/...)."""
    return html.replace(b'"/api/', b'"./api/')


def start_us(interval: int, top: int, auto_trade: bool, qty: int) -> None:
    us.CFG.update({"top": top, "interval": interval, "auto_trade": auto_trade, "paper_book": True, "qty": qty, "once": False})
    us.restore_from_prev()
    with us.LOCK:
        us.STATE["interval_min"] = interval
        us.STATE["watchlist"], us.STATE["added"] = us.load_watchlist()
    threading.Thread(target=us.loop, args=(top, interval), daemon=True).start()
    threading.Thread(target=us.live_pnl_loop, daemon=True).start()


def start_india(interval: int) -> None:
    symbols = india.session_watchlist()
    india.restore_from_prev()
    with india.LOCK:
        india.STATE["interval_min"] = interval
        india.STATE["watchlist"] = symbols
    try:
        from india_paper import flatten_after_hours_leftovers

        for line in flatten_after_hours_leftovers():
            print(f"  NSE leftover flattened: {line}")
    except Exception as exc:  # noqa: BLE001
        print(f"Could not flatten NSE after-hours leftovers: {exc}")
    threading.Thread(target=india.loop, args=(symbols, interval), daemon=True).start()
    threading.Thread(target=india._live_marks, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        if "/api/" not in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes | dict | list, content_type: str = "application/json; charset=utf-8") -> None:
        if not isinstance(body, bytes):
            body = json.dumps(body, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _tools_allowed(self) -> bool:
        # Trader tools run programs and write files: this PC only, and only via its own address.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if self.client_address[0] in LOOPBACK and host in ("127.0.0.1", "localhost"):
            return True
        self._send(403, {"error": "Trader tools only work on the PC running the app (http://127.0.0.1)."})
        return False

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        path = url.path
        if path in ("/", "/index.html"):
            return self._send(200, APP_HTML.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/apps":
            return self._send(200, {"us": ENABLED["us"], "in": ENABLED["in"],
                                    "tools": self.client_address[0] in LOOPBACK})

        if path.startswith("/us/") and ENABLED["us"]:
            sub = path[len("/us"):]
            if sub in ("/", "/index.html"):
                return self._send(200, relative_api(us.HTML_FILE.read_bytes()), "text/html; charset=utf-8")
            if sub == "/api/state":
                return self._send(200, us.public_state())
            if sub == "/api/paper":
                from internal_paper import refresh_mtm

                return self._send(200, refresh_mtm({}))

        if path.startswith("/in/") and ENABLED["in"]:
            sub = path[len("/in"):]
            if sub in ("/", "/index.html"):
                return self._send(200, relative_api(india.HTML_FILE.read_bytes()), "text/html; charset=utf-8")
            if sub in ("/api/state", "/state.json"):
                return self._send(200, india.public_state())
            if sub == "/api/paper":
                from india_paper import refresh_mtm

                return self._send(200, refresh_mtm({}))

        if path.startswith("/tools/"):
            if not self._tools_allowed():
                return
            sub = path[len("/tools"):]
            if sub in ("/", "/index.html"):
                return self._send(200, relative_api(DESK_HTML.read_bytes()), "text/html; charset=utf-8")
            if sub == "/api/tools":
                installed = {t["id"]: (Path(DESK.skills) / t["script"]).is_file() for t in TOOLS}
                return self._send(200, {"tools": TOOLS, "skills": DESK.skills, "data": DESK.data, "installed": installed})
            if sub == "/api/config":
                cfg = dict(CONFIG_DEFAULTS)
                cfg.update(DESK.read_config())
                return self._send(200, cfg)
            if sub == "/api/files":
                return self._send(200, {"files": DESK.files()})
            if sub == "/api/file":
                try:
                    rel = parse_qs(url.query).get("path", [""])[0]
                    return self._send(200, {"path": rel, "text": DESK.read_file(rel)})
                except ValueError as exc:
                    return self._send(404, {"error": str(exc)})

        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/us/api/scan" and ENABLED["us"]:
            us.WAKE.set()
            return self._send(200, {"ok": True})
        if path == "/in/api/scan" and ENABLED["in"]:
            india.WAKE.set()
            return self._send(200, {"ok": True})

        if path.startswith("/tools/api/"):
            if not self._tools_allowed():
                return
            # A JSON body can't be sent cross-site without a preflight, which this server never answers.
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._send(415, {"error": "JSON only"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 100_000)) or b"{}")
                if path == "/tools/api/run":
                    tool, action = find_action(body.get("tool"), body.get("action"))
                    if not action:
                        return self._send(404, {"error": "unknown tool"})
                    return self._send(200, DESK.run(tool, action, body.get("values") or {}))
                if path == "/tools/api/config":
                    return self._send(200, DESK.write_config(body))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})

        self._send(404, b"not found", "text/plain")


def main() -> None:
    p = argparse.ArgumentParser(description="US board + India board + Trader tools in one app")
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 lets a phone on the same Wi-Fi open the boards")
    p.add_argument("--interval", type=int, default=30, help="Minutes between scans (both boards)")
    p.add_argument("--top", type=int, default=10, help="US heat names to scan besides the watchlist")
    p.add_argument("--us-auto-trade", action="store_true",
                   help="Also send Alpaca PAPER orders on new US Buy/Sell (checked by trader-risk)")
    p.add_argument("--qty", type=int, default=10, help="US paper shares per new Buy/Sell")
    p.add_argument("--no-us", action="store_true", help="Skip the US board")
    p.add_argument("--no-india", action="store_true", help="Skip the India board")
    args = p.parse_args()

    interval = max(1, args.interval)
    ENABLED["us"], ENABLED["in"] = not args.no_us, not args.no_india
    if ENABLED["us"]:
        start_us(interval, max(1, args.top), args.us_auto_trade, max(1, args.qty))
    if ENABLED["in"]:
        start_india(interval)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Trading app on this PC: http://127.0.0.1:{args.port}")
    lan = us._lan_ip()
    if lan and args.host != "127.0.0.1":
        print(f"Boards on your phone (same Wi-Fi): http://{lan}:{args.port}")
    print(f"US board: {'on' if ENABLED['us'] else 'off'}"
          f"{' + Alpaca PAPER orders via trader-risk' if ENABLED['us'] and args.us_auto_trade else ''}"
          f" · India board: {'on' if ENABLED['in'] else 'off'} · scans every {interval} min")
    print("Keep this PC awake. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

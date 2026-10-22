"""Local web UI for the Trader skill pack.

Runs the pack's Python tools on your own computer and shows their output in a
browser page. Standard library only. Listens on 127.0.0.1, so only this
computer can reach it.

    python bot/trader_desk/server.py           # data in ./trader, skills in ~/.claude/skills (also built into bot/app.py)
    python bot/trader_desk/server.py --port 8765 --data D:/investing --skills D:/trader-skill-main

It never places an order. The broker tool is limited to showing tickets and
the decision log.
"""

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = 240

# Every runnable command. A field becomes command-line arguments:
#   text / number   -> flag value         (or a positional value if "flag" is absent)
#   list            -> flag v1 v2 ...     (space or comma separated input)
#   check           -> flag               (when ticked); "args" overrides what is added
#   select          -> flag value         (value must be one of "options")
#   choice          -> picked flag [value] (rule types for alerts add)
TOOLS = [
    {"id": "copycat", "name": "Copycat", "job": "Reverse-engineer an investor from their 13F",
     "script": "trader-copycat/edgar13f.py", "sec": True, "actions": [
        {"id": "find", "label": "Find investor", "args": ["find"], "fields": [
            {"name": "query", "label": "Name or person", "type": "list", "required": True, "placeholder": "buffett"},
            {"name": "sec", "label": "Also search every EDGAR filer", "type": "check", "flag": "--sec"}]},
        {"id": "filings", "label": "Filings", "args": ["filings"], "fields": [
            {"name": "cik", "label": "CIK", "type": "text", "required": True, "default": "1067983"},
            {"name": "limit", "label": "How many", "type": "number", "flag": "--limit"}]},
        {"id": "holdings", "label": "Holdings", "args": ["holdings"], "fields": [
            {"name": "cik", "label": "CIK", "type": "text", "required": True, "default": "1067983"},
            {"name": "period", "label": "Quarter end (YYYY-MM-DD, blank = newest)", "type": "text", "flag": "--period"},
            {"name": "top", "label": "Top N", "type": "number", "flag": "--top", "default": "15"},
            {"name": "combine", "label": "Combine share classes", "type": "check", "flag": "--combine", "default": True}]},
        {"id": "diff", "label": "Changes", "args": ["diff"], "fields": [
            {"name": "cik", "label": "CIK", "type": "text", "required": True, "default": "1067983"},
            {"name": "period", "label": "Quarter end (blank = newest)", "type": "text", "flag": "--period"},
            {"name": "combine", "label": "Combine share classes", "type": "check", "flag": "--combine", "default": True}]},
        {"id": "copy", "label": "Copy to targets", "args": ["copy"], "writes": "trader/targets.json", "fields": [
            {"name": "cik", "label": "CIK", "type": "text", "required": True, "default": "1067983"},
            {"name": "top", "label": "Top N", "type": "number", "flag": "--top", "default": "5"},
            {"name": "min_pct", "label": "Skip positions under %", "type": "number", "flag": "--min-pct"},
            {"name": "exclude", "label": "Leave out tickers", "type": "list", "flag": "--exclude", "placeholder": "KHC OXY"},
            {"name": "separate", "label": "Keep share classes apart", "type": "check", "flag": "--separate"},
            {"name": "dry_run", "label": "Preview only (don't write)", "type": "check", "flag": "--dry-run"}]},
    ]},
    {"id": "budget", "name": "Budget", "job": "Size every position to your budget",
     "script": "trader-budget/size.py", "actions": [
        {"id": "size", "label": "Size orders", "args": [], "writes": "trader/orders.json", "fields": [
            {"name": "budget", "label": "Budget $ (blank = from Settings)", "type": "number", "flag": "--budget"},
            {"name": "top", "label": "Keep only top N", "type": "number", "flag": "--top"},
            {"name": "whole", "label": "Whole shares only (uses trader/prices.json)", "type": "check",
             "args": ["--whole-shares", "--prices", "trader/prices.json"]},
            {"name": "cents", "label": "Size to the cent", "type": "check", "flag": "--cents"},
            {"name": "write", "label": "Write proposed orders", "type": "check", "flag": "--write", "default": True}]},
    ]},
    {"id": "risk", "name": "Risk", "job": "Check every proposed order against your limits",
     "script": "trader-risk/check.py", "actions": [
        {"id": "check", "label": "Check orders", "args": [], "fields": [
            {"name": "no_write", "label": "Don't record the verdicts", "type": "check", "flag": "--no-write"}]},
    ]},
    {"id": "broker", "name": "Broker", "job": "Order tickets (view only, never places orders)",
     "script": "trader-broker/ticket.py", "actions": [
        {"id": "show", "label": "Show tickets", "args": ["show"], "fields": []},
        {"id": "log", "label": "Today's log", "args": ["log"], "fields": []},
    ]},
    {"id": "news", "name": "News", "job": "Headlines and 8-Ks on what you hold",
     "script": "trader-news/news.py", "sec": True, "actions": [
        {"id": "scan", "label": "Scan news", "args": [], "fields": [
            {"name": "tickers", "label": "Tickers (blank = portfolio, else targets)", "type": "list", "flag": "--tickers",
             "placeholder": "AAPL AXP GOOGL KO BAC"},
            {"name": "hours", "label": "Last N hours", "type": "number", "flag": "--hours", "default": "24"},
            {"name": "all", "label": "Show items already seen", "type": "check", "flag": "--all"},
            {"name": "no_sec", "label": "Headlines only (no SEC)", "type": "check", "flag": "--no-sec"},
            {"name": "dry_run", "label": "Don't mark as seen", "type": "check", "flag": "--dry-run"}]},
    ]},
    {"id": "pelosi", "name": "Pelosi", "job": "Congress stock-trade disclosures",
     "script": "trader-pelosi/ptr.py", "actions": [
        {"id": "index", "label": "Filings", "args": ["index"], "fields": [
            {"name": "member", "label": "Member (last name)", "type": "text", "flag": "--member", "default": "pelosi"},
            {"name": "year", "label": "Year", "type": "number", "flag": "--year"},
            {"name": "since", "label": "Since (YYYY-MM-DD)", "type": "text", "flag": "--since"},
            {"name": "limit", "label": "How many", "type": "number", "flag": "--limit"}]},
        {"id": "new", "label": "New since last check", "args": ["new"], "fields": [
            {"name": "member", "label": "Member (last name)", "type": "text", "flag": "--member", "default": "pelosi"},
            {"name": "read", "label": "Download and read each new filing", "type": "check", "flag": "--read", "default": True},
            {"name": "dry_run", "label": "Don't mark as seen", "type": "check", "flag": "--dry-run"}]},
        {"id": "fetch", "label": "Read one filing", "args": ["fetch"], "fields": [
            {"name": "doc_id", "label": "Doc ID", "type": "text", "required": True, "placeholder": "20035553"},
            {"name": "year", "label": "Year", "type": "number", "flag": "--year"}]},
    ]},
    {"id": "analyst", "name": "Analyst", "job": "Reported earnings from SEC XBRL",
     "script": "trader-analyst/facts.py", "sec": True, "actions": [
        {"id": "facts", "label": "Earnings", "args": [], "fields": [
            {"name": "tickers", "label": "Tickers", "type": "list", "required": True, "placeholder": "AAPL KO"},
            {"name": "quarters", "label": "Quarters", "type": "number", "flag": "--quarters"},
            {"name": "no_filings", "label": "Skip 8-K / 10-Q links", "type": "check", "flag": "--no-filings"},
            {"name": "save", "label": "Save to trader/metrics.json (for the screener)", "type": "check",
             "args": ["--metrics", "trader/metrics.json"]}]},
    ]},
    {"id": "screener", "name": "Screener", "job": "Screen companies against your rules",
     "script": "trader-screener/screen.py", "actions": [
        {"id": "screen", "label": "Screen", "args": ["trader/metrics.json"], "fields": [
            {"name": "rules", "label": "Use my trader/rules.json (else the example rules)", "type": "check",
             "args": ["--rules", "trader/rules.json"]},
            {"name": "prices", "label": "Add prices from trader/prices.json", "type": "check",
             "args": ["--prices", "trader/prices.json"]},
            {"name": "top", "label": "Top N", "type": "number", "flag": "--top"},
            {"name": "out", "label": "Save shortlist to trader/shortlist.json", "type": "check",
             "args": ["--out", "trader/shortlist.json"]}]},
    ]},
    {"id": "tax", "name": "Tax", "job": "Lots, gains, harvesting, wash sales",
     "script": "trader-tax/lots.py", "actions": [
        {"id": "report", "label": "Gains report", "args": ["report"], "fields": [
            {"name": "lots", "label": "Show every lot", "type": "check", "flag": "--lots"}]},
        {"id": "sell", "label": "What-if sale", "args": ["sell"], "fields": [
            {"name": "ticker", "label": "Ticker", "type": "text", "required": True},
            {"name": "shares", "label": "Shares", "type": "number", "required": True},
            {"name": "price", "label": "Price $", "type": "number", "flag": "--price"},
            {"name": "method", "label": "Lot method", "type": "select", "flag": "--method",
             "options": ["fifo", "hifo"], "default": "fifo"}]},
        {"id": "harvest", "label": "Harvest losses", "args": ["harvest"], "fields": [
            {"name": "min_loss", "label": "Min loss $", "type": "number", "flag": "--min-loss", "default": "100"},
            {"name": "min_pct", "label": "Min loss %", "type": "number", "flag": "--min-pct"},
            {"name": "include_wash", "label": "Include wash-sale conflicts", "type": "check", "flag": "--include-wash"}]},
        {"id": "wash", "label": "Wash-sale check", "args": ["wash"], "fields": [
            {"name": "ticker", "label": "Ticker", "type": "text", "required": True},
            {"name": "date", "label": "Planned buy date", "type": "text", "flag": "--date"}]},
    ]},
    {"id": "alerts", "name": "Alerts", "job": "Price alerts and the NYSE clock",
     "script": "trader-alerts/alerts.py", "actions": [
        {"id": "clock", "label": "Market clock", "args": ["clock"], "fields": []},
        {"id": "quote", "label": "Quotes", "args": ["quote"], "fields": [
            {"name": "symbols", "label": "Symbols", "type": "list", "placeholder": "AAPL KO"},
            {"name": "holdings", "label": "Add my holdings and targets", "type": "check", "flag": "--holdings", "default": True},
            {"name": "source", "label": "Source", "type": "select", "flag": "--source", "options": ["yahoo", "stooq"], "default": "yahoo"},
            {"name": "write", "label": "Save to trader/prices.json", "type": "check", "flag": "--write"}]},
        {"id": "check", "label": "Check alerts", "args": ["check"], "fields": [
            {"name": "no_write", "label": "Don't record", "type": "check", "flag": "--no-write"}]},
        {"id": "list", "label": "My alerts", "args": ["list"], "fields": []},
        {"id": "add", "label": "Add alert", "args": ["add"], "fields": [
            {"name": "symbol", "label": "Symbol", "type": "text", "flag": "--symbol"},
            {"name": "rule", "label": "Rule", "type": "choice", "required": True,
             "options": [["--above", "Price above $"], ["--below", "Price below $"], ["--stop", "Stop at $"],
                         ["--pct", "Moves by %"], ["--opening-bell", "Opening bell"]],
             "novalue": ["--opening-bell"]},
            {"name": "rearm", "label": "Re-arm after it rings", "type": "check", "flag": "--rearm"},
            {"name": "note", "label": "Note", "type": "text", "flag": "--note"}]},
        {"id": "reset", "label": "Re-arm alert", "args": ["reset"], "fields": [
            {"name": "id", "label": "Alert ID", "type": "text", "required": True}]},
    ]},
    {"id": "rebalance", "name": "Rebalance", "job": "Bring the portfolio back to target weights",
     "script": "trader-rebalance/rebalance.py", "actions": [
        {"id": "drift", "label": "Drift table", "args": [], "fields": [
            {"name": "band", "label": "Drift band (points)", "type": "number", "flag": "--band", "default": "5"},
            {"name": "sell_untracked", "label": "Sell holdings not in targets", "type": "check", "flag": "--sell-untracked"},
            {"name": "write", "label": "Write proposed orders", "type": "check", "flag": "--write"}]},
    ]},
]

# Settings the page may change in trader/config.json, with their types.
CONFIG_KEYS = {
    "budget": float, "cash_buffer_pct": float, "max_position_pct": float, "max_order_usd": float,
    "min_order_usd": float, "max_orders_per_day": int, "fractional": bool, "broker": str,
    "blocked": list, "sec_user_agent": str,
}
CONFIG_DEFAULTS = {
    "budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 25, "max_order_usd": 2000,
    "min_order_usd": 5, "max_orders_per_day": 10, "fractional": True, "broker": "alpaca", "paper": True,
    "blocked": [], "allow_options": False, "allow_margin": False, "allow_short": False, "sec_user_agent": "",
}


def find_action(tool_id, action_id):
    for t in TOOLS:
        if t["id"] == tool_id:
            for a in t["actions"]:
                if a["id"] == action_id:
                    return t, a
    return None, None


def value_ok(v):
    # Typed values must never be read as an option.
    return v and not v.startswith("-")


def build_args(action, values):
    """Turn the form values into an argument list, or raise ValueError."""
    positional, flags = [], []
    for f in action["fields"]:
        v = values.get(f["name"])
        kind = f["type"]
        if kind == "check":
            if v is True:
                flags += f.get("args") or [f["flag"]]
            continue
        if kind == "choice":
            flag = (v or {}).get("flag") if isinstance(v, dict) else None
            opts = [o[0] for o in f["options"]]
            if not flag:
                if f.get("required"):
                    raise ValueError("%s is required" % f["label"])
                continue
            if flag not in opts:
                raise ValueError("bad %s" % f["label"])
            flags.append(flag)
            if flag not in f.get("novalue", []):
                val = str(v.get("value", "")).strip()
                try:
                    float(val)
                except ValueError:
                    raise ValueError("%s needs a number" % f["label"])
                flags.append(val)
            continue
        if kind == "list":
            items = [x for x in str(v or "").replace(",", " ").split() if x]
            if not items:
                if f.get("required"):
                    raise ValueError("%s is required" % f["label"])
                continue
            if not all(value_ok(x) for x in items):
                raise ValueError("bad value in %s" % f["label"])
            if "flag" in f:
                flags += [f["flag"]] + items
            else:
                positional += items
            continue
        v = str(v if v is not None else "").strip()
        if not v:
            if f.get("required"):
                raise ValueError("%s is required" % f["label"])
            continue
        if kind == "number":
            try:
                float(v)
            except ValueError:
                raise ValueError("%s must be a number" % f["label"])
            if v.startswith("-"):
                raise ValueError("%s must be positive" % f["label"])
        elif kind == "select":
            if v not in f["options"]:
                raise ValueError("bad %s" % f["label"])
        elif not value_ok(v):
            raise ValueError("bad value in %s" % f["label"])
        if "flag" in f:
            flags += [f["flag"], v]
        else:
            positional.append(v)
    return list(action["args"]) + positional + flags


class App:
    def __init__(self, skills, data):
        self.skills = skills
        self.data = data
        self.trader = os.path.join(data, "trader")

    def config_path(self):
        return os.path.join(self.trader, "config.json")

    def read_config(self):
        try:
            with open(self.config_path(), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def write_config(self, incoming):
        cfg = dict(CONFIG_DEFAULTS)
        cfg.update(self.read_config())
        for key, typ in CONFIG_KEYS.items():
            if key not in incoming:
                continue
            v = incoming[key]
            if typ is list:
                v = [x.strip().upper() for x in str(v).replace(",", " ").split() if x.strip()]
            elif typ is bool:
                v = bool(v)
            elif typ is str:
                v = str(v).strip()
            else:
                v = typ(float(v))
                if v < 0:
                    raise ValueError("%s must be positive" % key)
            cfg[key] = v
        os.makedirs(self.trader, exist_ok=True)
        with open(self.config_path(), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        return cfg

    def run(self, tool, action, values):
        args = build_args(action, values)
        script = os.path.join(self.skills, tool["script"])
        if not os.path.isfile(script):
            return {"ok": False, "code": -1, "cmd": tool["script"], "output": "Not found: %s\nInstall the skills or pass --skills." % script}
        os.makedirs(self.trader, exist_ok=True)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        cmd = [sys.executable, script] + args
        shown = "python " + tool["script"] + " " + " ".join(args)
        try:
            p = subprocess.run(cmd, cwd=self.data, env=env, capture_output=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "code": -1, "cmd": shown, "output": "Stopped after %d seconds." % TIMEOUT}
        out = p.stdout.decode("utf-8", "replace")
        err = p.stderr.decode("utf-8", "replace")
        text = out + (("\n" if out and err else "") + err if err else "")
        return {"ok": p.returncode == 0, "code": p.returncode, "cmd": shown, "output": text.rstrip() or "(no output)"}

    def files(self):
        found = []
        for root, _, names in os.walk(self.trader):
            for n in names:
                if n.endswith((".json", ".csv", ".txt")):
                    full = os.path.join(root, n)
                    rel = os.path.relpath(full, self.data).replace("\\", "/")
                    st = os.stat(full)
                    found.append({"path": rel, "size": st.st_size, "mtime": int(st.st_mtime)})
        return sorted(found, key=lambda f: f["path"])

    def read_file(self, rel):
        full = os.path.realpath(os.path.join(self.data, rel))
        base = os.path.realpath(self.trader)
        if not full.startswith(base + os.sep) or not os.path.isfile(full):
            raise ValueError("not a file in trader/")
        with open(full, encoding="utf-8", errors="replace") as fh:
            return fh.read(2_000_000)


def make_handler(app, port):
    allowed_hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            sys.stderr.write("  %s\n" % (fmt % a))

        def send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def host_ok(self):
            # Blocks other websites from reaching this server by DNS tricks.
            if self.headers.get("Host") not in allowed_hosts:
                self.send(403, {"error": "forbidden host"})
                return False
            return True

        def do_GET(self):
            if not self.host_ok():
                return
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                with open(os.path.join(HERE, "index.html"), "rb") as fh:
                    return self.send(200, fh.read(), "text/html")
            if url.path == "/api/tools":
                return self.send(200, {"tools": TOOLS, "skills": app.skills, "data": app.data,
                                       "installed": {t["id"]: os.path.isfile(os.path.join(app.skills, t["script"])) for t in TOOLS}})
            if url.path == "/api/config":
                cfg = dict(CONFIG_DEFAULTS)
                cfg.update(app.read_config())
                return self.send(200, cfg)
            if url.path == "/api/files":
                return self.send(200, {"files": app.files()})
            if url.path == "/api/file":
                try:
                    rel = parse_qs(url.query).get("path", [""])[0]
                    return self.send(200, {"path": rel, "text": app.read_file(rel)})
                except ValueError as e:
                    return self.send(404, {"error": str(e)})
            self.send(404, {"error": "not found"})

        def do_POST(self):
            if not self.host_ok():
                return
            # A JSON body can't be sent cross-site without a preflight, which we never answer.
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self.send(415, {"error": "JSON only"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 100_000)) or b"{}")
            except ValueError:
                return self.send(400, {"error": "bad JSON"})
            path = urlparse(self.path).path
            try:
                if path == "/api/run":
                    tool, action = find_action(body.get("tool"), body.get("action"))
                    if not action:
                        return self.send(404, {"error": "unknown tool"})
                    return self.send(200, app.run(tool, action, body.get("values") or {}))
                if path == "/api/config":
                    return self.send(200, app.write_config(body))
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            self.send(404, {"error": "not found"})

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Local web UI for the Trader skill pack.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--skills", default=os.path.join(os.path.expanduser("~"), ".claude", "skills"),
                    help="folder holding the trader-* skill folders")
    ap.add_argument("--data", default=os.getcwd(), help="folder whose trader/ subfolder holds your files")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    app = App(os.path.abspath(a.skills), os.path.abspath(a.data))
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(app, a.port))
    url = "http://127.0.0.1:%d/" % a.port
    print("Trader UI on %s\n  skills: %s\n  data:   %s\nCtrl+C to stop." % (url, app.skills, app.trader))
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

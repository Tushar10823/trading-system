"""
Bridge to the Trader skill pack (trader-risk + trader/targets.json).

Every --auto-trade order goes through trader-risk before it reaches Alpaca:
budget-sized, checked against trader/config.json (max order, per-stock cap,
cash buffer, blocked tickers, no shorts, daily order limit), and blocked if
anything fails. If the check itself can't run, the order is blocked too.

Where things live (override with env vars):
  TRADER_SKILLS  folder with the trader-* skills   (default ~/.claude/skills)
  TRADER_DATA    folder holding trader/             (default: repo root)

Files used:
  trader/config.json              your limits (budget, caps, blocked list)
  trader/targets.json             tickers to watch with --from-targets
  trader/state/bot_orders.json    orders this bot placed (for duplicates / daily limit)
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = Path(os.getenv("TRADER_SKILLS") or Path.home() / ".claude" / "skills")
TRADER_DIR = Path(os.getenv("TRADER_DATA") or REPO_ROOT) / "trader"
CONFIG_FILE = TRADER_DIR / "config.json"
TARGETS_FILE = TRADER_DIR / "targets.json"
BOT_STATE_FILE = TRADER_DIR / "state" / "bot_orders.json"
ET = ZoneInfo("America/New_York")

_risk_module = None


class BridgeError(Exception):
    pass


def _risk():
    """Import trader-risk/check.py from the installed skills."""
    global _risk_module
    if _risk_module is None:
        path = SKILLS_DIR / "trader-risk" / "check.py"
        if not path.exists():
            raise BridgeError(f"trader-risk not found at {path} (set TRADER_SKILLS)")
        spec = importlib.util.spec_from_file_location("trader_risk_check", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _risk_module = mod
    return _risk_module


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise BridgeError(f"{path} is not valid JSON: {exc}") from exc


def load_config() -> dict[str, Any]:
    cfg = _read_json(CONFIG_FILE)
    if not isinstance(cfg, dict):
        raise BridgeError(f"no limits file at {CONFIG_FILE}; auto-trade needs one")
    return cfg


def load_target_symbols() -> list[str]:
    """Tickers from trader/targets.json (written by trader-copycat or trader-screener)."""
    doc = _read_json(TARGETS_FILE)
    if doc is None:
        raise BridgeError(f"no targets at {TARGETS_FILE}; run trader-copycat first")
    rows = (doc.get("weights") or doc.get("targets") or []) if isinstance(doc, dict) else doc
    symbols = []
    for row in rows:
        sym = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if sym and sym not in symbols:
            symbols.append(sym)
    if not symbols:
        raise BridgeError(f"{TARGETS_FILE} has no tickers")
    return symbols


def account_snapshot(client: Any) -> tuple[dict[str, Any], dict[str, float]]:
    """The Alpaca paper account as trader-risk's portfolio + prices."""
    account = client.get_account()
    positions, prices = [], {}
    for p in client.get_all_positions():
        sym = str(p.symbol).upper()
        positions.append({"ticker": sym, "shares": float(p.qty)})
        prices[sym] = float(p.current_price)
    return {"cash": float(account.cash), "positions": positions}, prices


def _today() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d")


def _bot_state() -> dict[str, Any]:
    doc = _read_json(BOT_STATE_FILE)
    return doc if isinstance(doc, dict) else {"orders": []}


def max_buy_usd(cfg: dict[str, Any], portfolio: dict[str, Any], prices: dict[str, float], symbol: str) -> float:
    """Largest buy in $ that stays inside max order, the per-stock cap and the cash buffer."""
    cash = portfolio["cash"]
    values = {p["ticker"]: p["shares"] * prices.get(p["ticker"], 0.0) for p in portfolio["positions"]}
    total = cash + sum(values.values())
    room = [
        float(cfg.get("max_order_usd") or math.inf),
        total * float(cfg.get("max_position_pct") or 100) / 100 - values.get(symbol, 0.0),
        cash - total * float(cfg.get("cash_buffer_pct") or 0) / 100,
    ]
    return max(0.0, min(room))


def size_buy(client: Any, symbol: str, price: float, wanted_usd: float) -> int:
    """Whole shares for a buy: the bot's own size, cut down to what trader-risk allows."""
    cfg = load_config()
    portfolio, prices = account_snapshot(client)
    prices[symbol] = price
    usd = min(wanted_usd, max_buy_usd(cfg, portfolio, prices, symbol))
    return int(usd // price) if price > 0 else 0


def check_order(client: Any, symbol: str, side: str, qty: float, price: float) -> tuple[bool, list[str]]:
    """Run trader-risk on one market day order. Returns (passed, reasons). Fails closed."""
    try:
        risk = _risk()
        cfg = load_config()
        portfolio, prices = account_snapshot(client)
        prices[symbol] = price
        order = {"symbol": symbol, "side": side.lower(), "qty": qty, "type": "market", "time_in_force": "day"}
        res = risk.check([order], cfg, portfolio, prices, _bot_state(), _today())
        r = res["results"][0]
        return r["verdict"] == "PASS", list(r["reasons"])
    except Exception as exc:  # noqa: BLE001
        return False, [f"risk check could not run: {exc}"]


def record_placed(symbol: str, side: str, qty: float, order_id: str) -> None:
    """Remember a placed order so trader-risk counts it for duplicates and the daily limit."""
    state = _bot_state()
    state.setdefault("orders", []).append({
        "symbol": symbol,
        "side": side.lower(),
        "qty": qty,
        "status": "placed",
        "date": _today(),
        "at": datetime.now(timezone.utc).isoformat(),
        "broker_id": order_id,
    })
    BOT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BOT_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def blocked_result(symbol: str, side: str, qty: float, reasons: list[str]) -> dict[str, Any]:
    """The execute_auto_trade() result for an order trader-risk stopped."""
    return {
        "order_id": "",
        "order_status": "blocked_by_risk",
        "notes": f"trader-risk BLOCK {side} {qty} {symbol}: " + "; ".join(reasons),
        "side": "",
        "qty": 0,
    }

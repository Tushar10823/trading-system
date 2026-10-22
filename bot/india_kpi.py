"""
NSE paper KPIs from the Indian-market evaluation spec.

Computed on closed trades, net of the paper book's large-cap cost model.
Accuracy alone is never the success metric.
"""

from __future__ import annotations

from typing import Any

MIN_TRADES_TRUST = 100
MIN_TRADES_SHOW = 10
PAYOFF_TARGET = 1.5
WIN_RATE_IF_PAYOFF_NEAR_1 = 0.55
PROFIT_FACTOR_TARGET = 1.3
MAX_DRAWDOWN_TARGET = 0.20
KILL_SWITCH_DD = 0.15
SHARPE_TARGET = 1.0
SORTINO_TARGET = 1.5
CALMAR_TARGET = 1.0
RISK_FREE = 0.07


def _closed_pnls(trades: list[dict[str, Any]]) -> list[float]:
    pnls: list[float] = []
    for t in trades or []:
        if str(t.get("action", "")).upper() != "CLOSE":
            continue
        try:
            pnls.append(float(t.get("pnl") or 0))
        except (TypeError, ValueError):
            continue
    return pnls


def _max_drawdown(equity_points: list[float]) -> float:
    peak = None
    max_dd = 0.0
    for eq in equity_points:
        if peak is None or eq > peak:
            peak = eq
        if peak and peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def evaluate_paper(book: dict[str, Any]) -> dict[str, Any]:
    start = float(book.get("starting_cash") or 0) or 1.0
    cash = float(book.get("cash") or start)
    open_pnl = sum(float(p.get("pnl") or 0) for p in book.get("positions") or [])
    equity = cash + open_pnl
    trades = list(book.get("trades") or [])
    pnls = _closed_pnls(trades)
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    flats = [p for p in pnls if p == 0]
    win_n = len(wins)
    loss_n = len(losses)
    win_rate = (win_n / n) if n else None
    avg_win = (sum(wins) / win_n) if win_n else None
    avg_loss = (abs(sum(losses) / loss_n) if loss_n else None)
    payoff = (avg_win / avg_loss) if avg_win and avg_loss else None
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss else (None if not wins else float("inf"))
    loss_rate = (loss_n / n) if n else None
    expectancy = None
    if n and avg_win is not None:
        expectancy = (win_rate or 0) * avg_win - (loss_rate or 0) * (avg_loss or 0)

    running = start
    curve = [start]
    for p in pnls:
        running += p
        curve.append(running)
    curve.append(equity)
    max_dd = _max_drawdown(curve)
    total_return = (equity / start) - 1.0
    kill = max_dd >= KILL_SWITCH_DD or (start - equity) / start >= KILL_SWITCH_DD

    payoff_ok = False
    if payoff is not None and payoff > PAYOFF_TARGET:
        payoff_ok = True
    elif payoff is not None and payoff >= 0.9 and win_rate is not None and win_rate > WIN_RATE_IF_PAYOFF_NEAR_1:
        payoff_ok = True
    elif avg_loss is None and win_n and not loss_n and n >= MIN_TRADES_SHOW:
        payoff_ok = True

    pf_val = profit_factor
    pf_ok = pf_val is not None and pf_val > PROFIT_FACTOR_TARGET
    exp_ok = expectancy is not None and expectancy > 0
    dd_ok = max_dd < MAX_DRAWDOWN_TARGET
    sample_ok = n >= MIN_TRADES_TRUST

    gates = [
        {"id": "sample", "label": f"At least {MIN_TRADES_TRUST} closed trades", "pass": sample_ok, "value": n},
        {"id": "expectancy", "label": "Expectancy per trade > 0 (net of costs)", "pass": exp_ok, "value": expectancy},
        {"id": "profit_factor", "label": f"Profit factor > {PROFIT_FACTOR_TARGET}", "pass": pf_ok, "value": pf_val},
        {
            "id": "payoff",
            "label": f"Payoff > {PAYOFF_TARGET} (or win rate > 55% if payoff ~1)",
            "pass": payoff_ok,
            "value": payoff,
        },
        {
            "id": "drawdown",
            "label": f"Max drawdown < {MAX_DRAWDOWN_TARGET:.0%}",
            "pass": dd_ok,
            "value": max_dd,
        },
    ]
    scored = [g for g in gates if g["id"] != "sample" or n >= MIN_TRADES_SHOW]
    passed = sum(1 for g in gates if g["pass"])
    sample_factor = min(1.0, n / MIN_TRADES_TRUST) if n else 0.0
    live_factor = (passed / len(gates)) if gates else 0.0
    confidence = round(100 * (0.35 * sample_factor + 0.65 * live_factor), 1)
    if n < MIN_TRADES_SHOW:
        confidence = 0.0
        verdict = f"Too few closed trades ({n}). Spec wants {MIN_TRADES_TRUST}+ before trusting any statistic."
    elif not sample_ok:
        verdict = (
            f"{n} closed trades — track live, but do not treat KPIs as proven "
            f"(spec minimum {MIN_TRADES_TRUST})."
        )
    elif all(g["pass"] for g in gates):
        verdict = "Paper KPIs currently pass the spec gates. Still paper research, not advice."
    else:
        failed = [g["id"] for g in gates if not g["pass"]]
        verdict = "Not yet accepted: failing " + ", ".join(failed) + "."

    def _r(v: float | None, digits: int = 2) -> float | None:
        if v is None:
            return None
        if v == float("inf"):
            return None
        return round(v, digits)

    return {
        "trades": n,
        "wins": win_n,
        "losses": loss_n,
        "flats": len(flats),
        "win_rate": _r(win_rate, 4) if win_rate is not None else None,
        "avg_win": _r(avg_win),
        "avg_loss": _r(avg_loss),
        "payoff_ratio": _r(payoff, 3),
        "profit_factor": _r(pf_val, 3) if pf_val != float("inf") else None,
        "profit_factor_infinite": pf_val == float("inf"),
        "expectancy": _r(expectancy),
        "max_drawdown": _r(max_dd, 4),
        "total_return": _r(total_return, 4),
        "equity": round(equity, 2),
        "starting_cash": round(start, 2),
        "sharpe": None,
        "sortino": None,
        "cagr": None,
        "calmar": None,
        "kill_switch": kill,
        "kill_switch_limit": KILL_SWITCH_DD,
        "confidence": confidence,
        "verdict": verdict,
        "gates": gates,
        "targets": {
            "payoff_ratio": PAYOFF_TARGET,
            "profit_factor": PROFIT_FACTOR_TARGET,
            "max_drawdown": MAX_DRAWDOWN_TARGET,
            "min_trades": MIN_TRADES_TRUST,
            "sharpe": SHARPE_TARGET,
            "sortino": SORTINO_TARGET,
            "calmar": CALMAR_TARGET,
            "risk_free": RISK_FREE,
        },
        "cost_note": (
            "Net of 0.08% per side (large-cap slippage + charges band). "
            "CAGR/Sharpe/Sortino need a longer dated equity series."
        ),
        "scored_gates": len(scored),
        "passed_gates": passed,
    }

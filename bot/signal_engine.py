"""
Phase 3 — Signal combiner.

Takes indicator labels (bullish / bearish / neutral), scores them, and emits
one of: BUY | SELL | HOLD, plus which indicators drove the decision.

Tune behavior via the constants at the top of this file — not buried in logic.
"""

from __future__ import annotations

from typing import Any

from indicators import evaluate_all

# ---------------------------------------------------------------------------
# Tunable constants (edit these)
# ---------------------------------------------------------------------------

# Points awarded for each label
SCORE_BULLISH = 1
SCORE_BEARISH = -1
SCORE_NEUTRAL = 0

# Optional per-indicator weights (1.0 = equal weight). Raise a weight to
# make that indicator matter more in the final score.
INDICATOR_WEIGHTS: dict[str, float] = {
    "EMA crossover": 1.0,
    "RSI(14)": 1.0,
    "MACD": 1.0,
    "Bollinger Bands(20,2)": 1.0,
    "Volume vs 20d avg": 1.0,
}

# Final decision thresholds on the weighted sum
#   score >= BUY_THRESHOLD  -> BUY
#   score <= SELL_THRESHOLD -> SELL
#   otherwise               -> HOLD
BUY_THRESHOLD = 2.0
SELL_THRESHOLD = -2.0

LABEL_TO_SCORE = {
    "bullish": SCORE_BULLISH,
    "bearish": SCORE_BEARISH,
    "neutral": SCORE_NEUTRAL,
}


def _weight_for(name: str) -> float:
    return float(INDICATOR_WEIGHTS.get(name, 1.0))


def combine_labels(indicator_results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Score indicator labels and return a full signal payload.

    Returns keys:
      signal, score, buy_threshold, sell_threshold,
      drivers (bullish/bearish/neutral lists),
      contributions (per-indicator breakdown),
      reasoning (plain-English summary)
    """
    contributions: list[dict[str, Any]] = []
    bullish_drivers: list[str] = []
    bearish_drivers: list[str] = []
    neutral_drivers: list[str] = []
    total = 0.0

    for item in indicator_results:
        name = item["name"]
        label = item["label"]
        base = LABEL_TO_SCORE.get(label, 0)
        weight = _weight_for(name)
        points = base * weight
        total += points

        contributions.append(
            {
                "indicator": name,
                "label": label,
                "weight": weight,
                "points": points,
                "detail": item.get("detail", ""),
            }
        )

        if label == "bullish":
            bullish_drivers.append(name)
        elif label == "bearish":
            bearish_drivers.append(name)
        else:
            neutral_drivers.append(name)

    if total >= BUY_THRESHOLD:
        signal = "BUY"
    elif total <= SELL_THRESHOLD:
        signal = "SELL"
    else:
        signal = "HOLD"

    reasoning_parts = [
        f"score={total:.1f} (BUY>={BUY_THRESHOLD:g}, SELL<={SELL_THRESHOLD:g})",
    ]
    if bullish_drivers:
        reasoning_parts.append("bullish: " + ", ".join(bullish_drivers))
    if bearish_drivers:
        reasoning_parts.append("bearish: " + ", ".join(bearish_drivers))
    if neutral_drivers:
        reasoning_parts.append("neutral: " + ", ".join(neutral_drivers))

    return {
        "signal": signal,
        "score": round(total, 2),
        "buy_threshold": BUY_THRESHOLD,
        "sell_threshold": SELL_THRESHOLD,
        "drivers": {
            "bullish": bullish_drivers,
            "bearish": bearish_drivers,
            "neutral": neutral_drivers,
        },
        "contributions": contributions,
        "reasoning": " | ".join(reasoning_parts),
    }


def generate_signal(df) -> dict[str, Any]:
    """Run indicators on an OHLCV frame, then combine into BUY/SELL/HOLD."""
    results = evaluate_all(df)
    combined = combine_labels(results)
    combined["indicators"] = results
    return combined


def format_signal_report(symbol: str, close: float, payload: dict[str, Any]) -> str:
    """Human-readable multi-line report for console output."""
    lines = [
        "=" * 60,
        f"Signal: {payload['signal']}  |  {symbol} @ {close:.2f}",
        f"Score:  {payload['score']}  "
        f"(BUY>={payload['buy_threshold']}, SELL<={payload['sell_threshold']})",
        "-" * 60,
        "Contributions:",
    ]
    for c in payload["contributions"]:
        lines.append(
            f"  {c['indicator']:<24} {c['label']:<8} "
            f"points={c['points']:+.1f}  ({c['detail']})"
        )
    lines.append("-" * 60)
    lines.append(f"Drivers bullish : {', '.join(payload['drivers']['bullish']) or '-'}")
    lines.append(f"Drivers bearish : {', '.join(payload['drivers']['bearish']) or '-'}")
    lines.append(f"Drivers neutral : {', '.join(payload['drivers']['neutral']) or '-'}")
    lines.append(f"Reasoning: {payload['reasoning']}")
    lines.append("=" * 60)
    return "\n".join(lines)

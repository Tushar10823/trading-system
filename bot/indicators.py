"""
Phase 2 — Technical indicator engine.

Each function takes a pandas OHLCV DataFrame (columns: open, high, low, close,
volume) and returns a dict with raw values plus a label:

    bullish | bearish | neutral

Label rules are documented next to each function so they stay easy to tweak.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pandas_ta as ta

Label = str  # "bullish" | "bearish" | "neutral"


def _require_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = required - {c.lower() for c in df.columns}
    if missing:
        raise ValueError(f"DataFrame missing columns: {sorted(missing)}")

    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    if out.empty:
        raise ValueError("DataFrame is empty")
    return out


def _last(series: pd.Series) -> float:
    value = series.dropna().iloc[-1]
    return float(value)


# ---------------------------------------------------------------------------
# Individual indicators
# ---------------------------------------------------------------------------


def ema_crossover(df: pd.DataFrame) -> dict[str, Any]:
    """EMA(9) vs EMA(21) — trend direction via crossover / relative position.

    Labels:
      - bullish: EMA9 > EMA21 (short-term trend above longer-term)
      - bearish: EMA9 < EMA21
      - neutral: equal (rare)
    """
    data = _require_ohlcv(df)
    ema9 = ta.ema(data["close"], length=9)
    ema21 = ta.ema(data["close"], length=21)
    e9, e21 = _last(ema9), _last(ema21)

    if e9 > e21:
        label: Label = "bullish"
    elif e9 < e21:
        label = "bearish"
    else:
        label = "neutral"

    return {
        "name": "EMA crossover",
        "label": label,
        "ema9": round(e9, 4),
        "ema21": round(e21, 4),
        "detail": f"EMA9={e9:.2f} vs EMA21={e21:.2f}",
    }


def rsi(df: pd.DataFrame, length: int = 14) -> dict[str, Any]:
    """RSI — mean-reversion extremes.

    Labels:
      - bullish: RSI < 30 (oversold)
      - bearish: RSI > 70 (overbought)
      - neutral: 30 ≤ RSI ≤ 70
    """
    data = _require_ohlcv(df)
    series = ta.rsi(data["close"], length=length)
    value = _last(series)

    if value < 30:
        label: Label = "bullish"
    elif value > 70:
        label = "bearish"
    else:
        label = "neutral"

    return {
        "name": "RSI(14)",
        "label": label,
        "value": round(value, 2),
        "detail": f"RSI={value:.2f}",
    }


def macd(df: pd.DataFrame) -> dict[str, Any]:
    """MACD(12,26,9) — momentum acceleration / deceleration.

    Labels (line vs signal; histogram confirms strength):
      - bullish: MACD line > signal line (positive momentum)
      - bearish: MACD line < signal line (negative momentum)
      - neutral: equal
    """
    data = _require_ohlcv(df)
    macd_df = ta.macd(data["close"], fast=12, slow=26, signal=9)
    if macd_df is None or macd_df.empty:
        raise ValueError("MACD calculation returned no data (need more bars)")

    line = _last(macd_df["MACD_12_26_9"])
    hist = _last(macd_df["MACDh_12_26_9"])
    signal = _last(macd_df["MACDs_12_26_9"])

    if line > signal:
        label: Label = "bullish"
    elif line < signal:
        label = "bearish"
    else:
        label = "neutral"

    accel = "accelerating" if hist > 0 else "decelerating" if hist < 0 else "flat"

    return {
        "name": "MACD",
        "label": label,
        "macd": round(line, 4),
        "signal": round(signal, 4),
        "histogram": round(hist, 4),
        "detail": f"MACD={line:.4f} signal={signal:.4f} hist={hist:.4f} ({accel})",
    }


def bollinger_bands(df: pd.DataFrame, length: int = 20, std: float = 2.0) -> dict[str, Any]:
    """Bollinger Bands(20, 2) — price stretch from the mean.

    Labels (mean-reversion framing):
      - bullish: close at or below lower band (stretched down)
      - bearish: close at or above upper band (stretched up)
      - neutral: inside the bands
    """
    data = _require_ohlcv(df)
    bb = ta.bbands(data["close"], length=length, std=std)
    if bb is None or bb.empty:
        raise ValueError("Bollinger calculation returned no data (need more bars)")

    # Column names include the std value, e.g. BBL_20_2.0_2.0
    lower_col = [c for c in bb.columns if c.startswith("BBL_")][0]
    mid_col = [c for c in bb.columns if c.startswith("BBM_")][0]
    upper_col = [c for c in bb.columns if c.startswith("BBU_")][0]
    pct_col = [c for c in bb.columns if c.startswith("BBP_")][0]

    close = float(data["close"].iloc[-1])
    lower, mid, upper = _last(bb[lower_col]), _last(bb[mid_col]), _last(bb[upper_col])
    pct_b = _last(bb[pct_col])

    if close <= lower:
        label: Label = "bullish"
    elif close >= upper:
        label = "bearish"
    else:
        label = "neutral"

    return {
        "name": "Bollinger Bands(20,2)",
        "label": label,
        "close": round(close, 4),
        "lower": round(lower, 4),
        "mid": round(mid, 4),
        "upper": round(upper, 4),
        "percent_b": round(pct_b, 4),
        "detail": f"close={close:.2f} bands=[{lower:.2f}, {mid:.2f}, {upper:.2f}] %B={pct_b:.2f}",
    }


def volume_vs_average(df: pd.DataFrame, length: int = 20) -> dict[str, Any]:
    """Volume vs 20-day average — participation strength.

    Labels:
      - bullish: volume > 1.1 × 20-day average (elevated participation)
      - bearish: volume < 0.9 × 20-day average (light participation)
      - neutral: within ±10% of the average
    """
    data = _require_ohlcv(df)
    vol = data["volume"]
    avg = vol.rolling(window=length).mean()
    latest = float(vol.iloc[-1])
    avg_val = _last(avg)
    ratio = latest / avg_val if avg_val else 0.0

    if ratio > 1.1:
        label: Label = "bullish"
    elif ratio < 0.9:
        label = "bearish"
    else:
        label = "neutral"

    return {
        "name": "Volume vs 20d avg",
        "label": label,
        "volume": round(latest, 0),
        "avg_volume": round(avg_val, 0),
        "ratio": round(ratio, 3),
        "detail": f"vol={latest:,.0f} avg={avg_val:,.0f} ratio={ratio:.2f}x",
    }


def evaluate_all(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Run every indicator and return a list of result dicts (latest bar)."""
    return [
        ema_crossover(df),
        rsi(df),
        macd(df),
        bollinger_bands(df),
        volume_vs_average(df),
    ]


def results_table(results: list[dict[str, Any]]) -> pd.DataFrame:
    """Readable summary table: indicator | value summary | label."""
    rows = [
        {
            "indicator": r["name"],
            "values": r["detail"],
            "label": r["label"],
        }
        for r in results
    ]
    return pd.DataFrame(rows)

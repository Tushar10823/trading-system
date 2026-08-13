"""
Phase 5.5 — News + volatility day-trade idea scanner.

What it does:
  1) Pull recent market/stock headlines (NewsAPI + optional local n8n feed)
  2) Map headlines to liquid US tickers (Alpaca-tradable)
  3) Rank by intraday volatility (5-min ATR%) + news heat + simple sentiment
  4) Run intraday call engine on the top names
  5) Print ENTER / EXIT style calls for day trading research

Notes:
  - Moneycontrol / NSE / Groww are India-focused. This bot executes on Alpaca US
    paper. Indian RSS can still be collected via n8n for context, but trade
    suggestions here stay on US symbols Alpaca can fill.
  - YouTube is not scraped (unstable / ToS). Use news + price volatility instead.

Usage:
  python phase55_news_scanner.py
  python phase55_news_scanner.py --top 5
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

from intraday_calls import analyze_symbol, print_calls, log_calls
from market_data import fetch_intraday_bars

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
N8N_FEED = OUTPUT_DIR / "n8n_news_feed.json"
SCAN_LOG = OUTPUT_DIR / "phase55_scan.csv"

# Always run a call on these even if they miss the heat top-N
ALWAYS_INCLUDE = ["AAPL"]

# Liquid US names suitable for paper day-trading research on Alpaca
UNIVERSE = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
    "SPY",
    "QQQ",
    "AMD",
    "NFLX",
    "CRM",
    "AVGO",
    "INTC",
    "BABA",
    "PLTR",
    "COIN",
    "SMCI",
    "MSTR",
]

NAME_TO_TICKER = {
    "apple": "AAPL",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amazon": "AMZN",
    "meta": "META",
    "facebook": "META",
    "nvidia": "NVDA",
    "tesla": "TSLA",
    "netflix": "NFLX",
    "amd": "AMD",
    "intel": "INTC",
    "broadcom": "AVGO",
    "salesforce": "CRM",
    "alibaba": "BABA",
    "palantir": "PLTR",
    "coinbase": "COIN",
    "microstrategy": "MSTR",
    "strategy": "MSTR",
}

BULLISH_WORDS = {
    "surge",
    "soar",
    "rally",
    "beat",
    "beats",
    "record",
    "upgrade",
    "raises",
    "growth",
    "profit",
    "bullish",
    "breakout",
    "jump",
    "jumps",
    "high",
    "wins",
    "strong",
}
BEARISH_WORDS = {
    "fall",
    "falls",
    "drop",
    "drops",
    "plunge",
    "cut",
    "cuts",
    "miss",
    "misses",
    "downgrade",
    "lawsuit",
    "probe",
    "fraud",
    "weak",
    "bearish",
    "selloff",
    "crash",
    "layoff",
    "layoffs",
    "ban",
}


def load_env() -> None:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT.parent / ".env")


def news_api_key() -> str:
    key = os.getenv("NEWS_API_KEY", "").strip()
    if not key or key.startswith("your_"):
        raise RuntimeError(
            "NEWS_API_KEY missing. Add it to bot/.env or repo root .env"
        )
    return key


def fetch_newsapi_headlines(api_key: str, page_size: int = 50) -> list[dict[str, Any]]:
    """General market + mega-cap news for the last day."""
    url = "https://newsapi.org/v2/everything"
    query = (
        "(Apple OR Microsoft OR Google OR Amazon OR Meta OR Nvidia OR Tesla "
        "OR stocks OR Wall Street OR Nasdaq) AND (stock OR shares OR market)"
    )
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": api_key,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    articles = resp.json().get("articles", [])
    out = []
    for a in articles:
        out.append(
            {
                "source": (a.get("source") or {}).get("name") or "NewsAPI",
                "title": a.get("title") or "",
                "description": a.get("description") or "",
                "url": a.get("url") or "",
                "publishedAt": a.get("publishedAt") or "",
            }
        )
    return out


def load_n8n_feed() -> list[dict[str, Any]]:
    """Headlines from n8n workflow 03, stored in Postgres (same as workflow 01)."""
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return []
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("psycopg2 not installed - skip n8n Postgres feed")
        return []

    cleaned: list[dict[str, Any]] = []
    try:
        conn = psycopg2.connect(url)
        with conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT source, title, description, url, published_at
                    FROM news_feed
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                )
                for row in cur.fetchall():
                    cleaned.append(
                        {
                            "source": row.get("source") or "n8n",
                            "title": row.get("title") or "",
                            "description": row.get("description") or "",
                            "url": row.get("url") or "",
                            "publishedAt": str(row.get("published_at") or ""),
                        }
                    )
        conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"n8n Postgres feed unavailable: {exc}")
        return []
    return cleaned


def sentiment_score(text: str) -> int:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    score = 0
    for w in words:
        if w in BULLISH_WORDS:
            score += 1
        if w in BEARISH_WORDS:
            score -= 1
    return score


def extract_tickers(text: str) -> set[str]:
    found: set[str] = set()
    upper = text.upper()
    for t in UNIVERSE:
        if re.search(rf"\b{t}\b", upper):
            found.add(t)
    lower = text.lower()
    for name, ticker in NAME_TO_TICKER.items():
        if name in lower:
            found.add(ticker)
    return found


def atr_pct(df: pd.DataFrame, length: int = 14) -> float:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.tail(length).mean())
    last = float(close.iloc[-1])
    if last <= 0:
        return 0.0
    return (atr / last) * 100.0


def range_pct(df: pd.DataFrame, bars: int = 78) -> float:
    """Approx session range % over recent bars (~half day of 5m bars)."""
    window = df.tail(bars)
    hi = float(window["high"].max())
    lo = float(window["low"].min())
    mid = float(window["close"].iloc[-1])
    if mid <= 0:
        return 0.0
    return ((hi - lo) / mid) * 100.0


def aggregate_news(articles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "sentiment": 0, "headlines": []}
    )
    for a in articles:
        text = f"{a.get('title', '')} {a.get('description', '')}"
        tickers = extract_tickers(text)
        if not tickers:
            continue
        sent = sentiment_score(text)
        for t in tickers:
            bucket[t]["count"] += 1
            bucket[t]["sentiment"] += sent
            if a.get("title"):
                bucket[t]["headlines"].append(
                    {
                        "title": a["title"],
                        "source": a.get("source", ""),
                        "url": a.get("url", ""),
                    }
                )
    return bucket


def rank_candidates(
    news_map: dict[str, dict[str, Any]],
    min_news: int = 1,
    extra_symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Always score a core liquid set, boost those with news
    extra = {s.upper() for s in (extra_symbols or [])}
    symbols = sorted(set(UNIVERSE) | set(news_map.keys()) | extra)
    for sym in symbols:
        try:
            df = fetch_intraday_bars(sym, minutes=5, lookback_days=5, min_bars=40)
            vol = atr_pct(df)
            sess = range_pct(df)
            price = float(df["close"].iloc[-1])
        except Exception as exc:  # noqa: BLE001
            print(f"  skip vol {sym}: {exc}")
            continue

        n = news_map.get(sym, {"count": 0, "sentiment": 0, "headlines": []})
        news_count = int(n["count"])
        sent = int(n["sentiment"])
        # Composite: volatility dominates for day-trade amenability; news is catalyst
        score = (vol * 2.0) + (sess * 0.5) + (news_count * 1.5) + (sent * 0.5)
        rows.append(
            {
                "symbol": sym,
                "price": round(price, 2),
                "atr_pct": round(vol, 3),
                "range_pct": round(sess, 3),
                "news_count": news_count,
                "sentiment": sent,
                "heat_score": round(score, 2),
                "top_headline": (n["headlines"][0]["title"] if n["headlines"] else ""),
            }
        )

    rows.sort(key=lambda r: r["heat_score"], reverse=True)
    # Prefer names with at least some news when available; else pure vol
    with_news = [r for r in rows if r["news_count"] >= min_news]
    if with_news:
        # Keep high-vol names even without news as fillers
        extras = [r for r in rows if r["news_count"] < min_news]
        merged = with_news + extras
        # unique by symbol preserving order
        seen = set()
        ordered = []
        for r in merged:
            if r["symbol"] in seen:
                continue
            seen.add(r["symbol"])
            ordered.append(r)
        return ordered
    return rows


def save_scan(rows: list[dict[str, Any]]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(SCAN_LOG, index=False)


def collect_scan(
    top_n: int = 5,
    verbose: bool = True,
    extra_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Run news+vol ranking and intraday calls. Used by CLI, watcher, dashboard."""
    load_env()
    articles: list[dict[str, Any]] = []
    try:
        articles.extend(fetch_newsapi_headlines(news_api_key()))
        if verbose:
            print(f"NewsAPI articles: {len(articles)}")
    except Exception as exc:  # noqa: BLE001
        if verbose:
            print(f"NewsAPI failed: {exc}")

    n8n_articles = load_n8n_feed()
    if n8n_articles:
        if verbose:
            print(f"n8n Postgres feed articles (24h): {len(n8n_articles)}")
        articles.extend(n8n_articles)
    elif verbose:
        print("n8n Postgres feed empty - publish workflow 03 and execute it once")

    news_map = aggregate_news(articles)
    if verbose:
        print(f"Tickers mentioned in news: {', '.join(sorted(news_map)) or 'none'}")
        print("Scoring volatility on liquid universe...")
    ranked = rank_candidates(news_map, extra_symbols=extra_symbols)
    save_scan(ranked)

    if verbose and ranked:
        print("\nTop heat ranking (vol + news):")
        preview = pd.DataFrame(ranked[:10])[
            ["symbol", "price", "atr_pct", "range_pct", "news_count", "sentiment", "heat_score"]
        ]
        print(preview.to_string(index=False))

    heat = ranked[: max(1, top_n)]
    heat_syms = {r["symbol"] for r in heat}
    by_symbol = {r["symbol"]: r for r in ranked}
    pin_order = list(ALWAYS_INCLUDE) + [s.upper() for s in (extra_symbols or [])]
    pinned = []
    seen = set(heat_syms)
    for s in pin_order:
        if s in by_symbol and s not in seen:
            pinned.append(by_symbol[s])
            seen.add(s)
    top = pinned + heat
    if not top:
        top = heat
    if verbose:
        print("\nRunning intraday calls on top names...")
    calls: list[dict[str, Any]] = []
    for r in top:
        sym = r["symbol"]
        try:
            call = analyze_symbol(sym)
            call["heat_score"] = r["heat_score"]
            call["atr_pct"] = r["atr_pct"]
            call["news_count"] = r["news_count"]
            call["headline"] = r["top_headline"]
            calls.append(call)
            if verbose:
                print(f"  {sym}: {call['action']} @ {call['price']}")
        except Exception as exc:  # noqa: BLE001
            if verbose:
                print(f"  call failed {sym}: {exc}")

    if calls and verbose:
        log_calls(calls)
        print()
        print_calls(calls)
        print("\nWhy these names (catalysts):")
        for r in top:
            hl = r["top_headline"] or "(no mapped headline - volatility pick)"
            print(f"  {r['symbol']}: ATR%={r['atr_pct']} news={r['news_count']} | {hl[:100]}")

    return {"ranked": ranked, "calls": calls, "top": top}


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5.5 news + vol scanner")
    parser.add_argument("--top", type=int, default=5, help="How many names to call")
    args = parser.parse_args()

    print("=" * 72)
    print("PHASE 5.5 - News + volatility day-trade scanner (paper research)")
    print(f"UTC: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 72)
    collect_scan(top_n=args.top, verbose=True)
    print(f"\nScan CSV -> {SCAN_LOG}")
    print("Phase 5.5 complete. Paper research only - not financial advice.")


if __name__ == "__main__":
    main()

# Trading Signal Bot (Paper Trading)

Python bot that pulls Alpaca market data, computes technical indicators, emits Buy/Hold/Sell signals, backtests, and can run live against **Alpaca paper trading** on localhost. Telegram alerts come in a later phase.

Built phase-by-phase from the project build spec. **Paper trading only.**

## Prerequisites

- Python 3.11+ (this machine uses 3.12)
- Alpaca paper trading API keys

## Setup

**Linux / macOS:**

```bash
cd trading-system/bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

**Windows:**

```powershell
cd E:\AI\trading-system\bot
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set:

| Variable | What to put |
|---|---|
| `ALPACA_API_KEY` | Paper API key from Alpaca |
| `ALPACA_SECRET_KEY` | Paper secret key |
| `ALPACA_BASE_URL` | Leave as `https://paper-api.alpaca.markets` |

### How to get Alpaca paper keys

1. Sign up / log in at [https://app.alpaca.markets/signup](https://app.alpaca.markets/signup)
2. Make sure you are in **Paper Trading** (not Live)
3. Go to **API Keys** → generate a key pair
4. Paste them into `bot/.env`

Never commit `.env`. Never use live/real-money keys in this project.

## Phase 1 — Connection check

```powershell
cd E:\AI\trading-system\bot
.\venv\Scripts\Activate.ps1
python check_connection.py
```

Expected: account status printed, then the last 30 daily AAPL bars.

## Later phases (not built yet)

2. ~~Indicator engine~~  
3. ~~Signal combiner~~  
4. ~~Backtesting~~  
5. ~~Live paper trading loop (localhost)~~  
6. Telegram BUY/SELL pings  
7. Summary report  

## Phase 2 — Indicators

```powershell
cd E:\AI\trading-system\bot
.\venv\Scripts\Activate.ps1
python test_indicators.py
python test_indicators.py MSFT
```

## Phase 3 — Signal

```powershell
python test_signal.py AAPL
python test_signal.py MSFT
```

Tune weights/thresholds at the top of `signal_engine.py`.

## Phase 4 — Backtest

```powershell
python backtest.py
python backtest.py AAPL MSFT TSLA
```

Trade CSVs land in `bot/output/`.

## Phase 5 — Live paper (localhost)

```powershell
# Safe: log signal only (no orders)
python live_signal.py --symbol AAPL --once

# Loop every 15 minutes, still log-only
python live_signal.py --symbol AAPL --interval 15

# OPT-IN paper orders
python live_signal.py --symbol AAPL --once --auto-trade
```

Signals append to `output/live_signals.csv`. Paper fills (if enabled) go to `output/paper_trades.csv`.

## Intraday mode (1-min / 5-min)

```powershell
# One-shot 5-min bars
python live_intraday.py --symbol AAPL --bar 5 --once

# Loop every 5 minutes on 5-min bars (log only)
python live_intraday.py --symbol AAPL --bar 5 --interval 5

# Faster: 1-min bars, every 1 minute, 3 cycles then stop
python live_intraday.py --symbol AAPL --bar 1 --interval 1 --cycles 3
```

Logs: `output/live_intraday_signals.csv`

## Intraday day-trade calls (recommended)

```powershell
python intraday_calls.py
python intraday_calls.py AAPL TSLA GOOGL
python intraday_calls.py --loop 5
```

Uses 5‑min primary + 1‑min confirmation, with stop/target. Log: `output/intraday_calls.csv`

## Phase 5.5 — News + volatility ideas

```powershell
python phase55_news_scanner.py
python phase55_news_scanner.py --top 5
```

Pulls NewsAPI headlines, ranks liquid US names by **volatility + news heat**, then runs intraday calls on the top picks.

Optional n8n enrichment (same pattern as workflow 01):
1. `docker compose up -d` from repo root
2. Workflow `03 - Phase 5.5 News Feed` is imported and published
3. It writes NewsAPI + Moneycontrol RSS into Postgres `news_feed`
4. Trigger now: POST http://localhost:5678/webhook/phase55-news
5. Then run `python phase55_news_scanner.py --top 5`

Watch for reversals (idle unless a call flips or hits stop/target):

```powershell
python phase55_watch.py --top 5 --interval 30
```

## Localhost dashboard (recommended)

Keeps scanning every 30 minutes, shows IST times, and **auto-adds any stock that prints Buy or Sell**.

```powershell
cd E:\AI\trading-system\bot
.\venv\Scripts\Activate.ps1
python dashboard.py
```

Open http://127.0.0.1:8787 — leave this window running. Use **Scan now** if you do not want to wait for the next interval.

Do not run `phase55_watch.py` at the same time (duplicate scans).

### Phone (same Wi-Fi)

The dashboard must keep running **on this PC**. Cursor on the phone cannot start Python localhost.

1. Keep the PC awake and `python dashboard.py` running
2. Phone and PC on the same Wi-Fi
3. Open the LAN URL printed in the terminal, e.g. `http://192.168.x.x:8787`

If it does not load, allow Python through Windows Firewall for private networks. Keys stay in `bot/.env` on this PC and are never pushed to GitHub.

## Phone website (PC can be off)

GitHub Actions scans every 30 minutes and publishes the board to GitHub Pages:

**https://tushar10823.github.io/trading-system/**

Bookmark that URL on your phone. No local Python process is required.

Repo secrets (Settings → Secrets and variables → Actions): `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, optional `NEWS_API_KEY`. Paper keys only. The board page is public — it shows calls, not API keys.


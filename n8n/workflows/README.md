# n8n Workflow Setup Guide

After importing both workflows, configure these credentials in n8n (Settings → Credentials):

## 1. Trading Postgres

| Field    | Value              |
|----------|--------------------|
| Host     | `postgres`         |
| Port     | `5432`             |
| Database | `trading`          |
| User     | `trading`          |
| Password | (from your `.env`) |
| SSL      | Disabled           |

Assign this credential to all Postgres nodes in both workflows.

## 2. Alpaca Paper API (Header Auth)

| Field  | Value                        |
|--------|------------------------------|
| Name   | `APCA-API-KEY-ID`            |
| Value  | (your Alpaca API key)        |

Add a second header:
| Name   | `APCA-API-SECRET-KEY`        |
| Value  | (your Alpaca secret key)     |

Assign to the "Alpaca Paper Order" node in workflow 02.

## 3. Environment variables

These are passed via `docker-compose.yml` from your `.env` file:
- `ALPHA_VANTAGE_KEY`
- `NEWS_API_KEY`
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY`
- `DEFAULT_SYMBOLS`
- `CONFIDENCE_THRESHOLD`
- `OLLAMA_MODEL`

## 4. Activate workflows

1. Open workflow 02 first → save → **Publish** (registers the webhook)
2. Open workflow 01 → save → **Publish**
3. Import `03-phase55-news.json` → **Publish** (writes headlines into `news_feed`)
4. Test: Execute workflow 03, then run `python bot/phase55_news_scanner.py --top 5`

## Troubleshooting

- **Ollama unreachable from n8n**: Ensure Ollama is running on the host. The workflow uses `host.docker.internal:11434`.
- **Alpha Vantage rate limit**: Free tier allows 5 calls/min. With 2 symbols, keep the 30-min cron.
- **NewsAPI dev restriction**: Free tier only works on localhost during development.

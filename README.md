# Trading System MVP

Automated paper-trading system: n8n workflows collect market data, Ollama makes decisions, Alpaca executes paper trades, and a Next.js dashboard monitors everything.

## Quick start

### Linux / macOS

```bash
git clone <your-repo-url>
cd trading-system
chmod +x scripts/*.sh
./scripts/install.sh
```

Edit `.env` and `bot/.env` with your API keys, start **Docker**, then verify:

```bash
./scripts/verify.sh
```

### Windows

```powershell
cd E:\AI\trading-system
.\scripts\install.ps1
```

Restart your terminal, start **Docker Desktop**, then verify:

```powershell
.\scripts\verify.ps1
```

### 2. Configure environment

**Linux / macOS:**

```bash
cp .env.example .env
cp bot/.env.example bot/.env
# Edit both files with your API keys
```

**Windows:**

```powershell
copy .env.example .env
# Edit .env with your API keys
```

Sign up for free API keys:
- [Alpha Vantage](https://www.alphavantage.co/support/#api-key)
- [NewsAPI](https://newsapi.org/register)
- [Alpaca Paper](https://app.alpaca.markets/signup)

### 3. Start infrastructure

```bash
docker compose up -d
```

Also start **Ollama** on the host (required for workflow 02):

```bash
ollama serve          # if not already running
ollama pull llama3.2
```

Services:
- **n8n** — http://localhost:5678 (admin / password from `.env`)
- **Adminer** — http://localhost:8080 (DB UI)
- **Postgres** — localhost:5432

### 4. Import n8n workflows

1. Open http://localhost:5678
2. **Workflows → Import from File**
3. Import `n8n/workflows/01-data-collection.json`
4. Import `n8n/workflows/02-analyze-and-trade.json`
5. Configure Postgres credentials in n8n (host: `postgres`, user/password from `.env`)
6. Activate both workflows

### 5. Start dashboard

```bash
cd web
npm install   # skip if ./scripts/install.sh already ran
npm run dev
```

Open http://localhost:3000

### 6. Run tests

**Linux / macOS:** `./scripts/e2e-test.sh`  
**Windows:** `.\scripts\e2e-test.ps1`

## Architecture

- **Stage 1** — Cron every 30 min → Alpha Vantage + NewsAPI → Postgres
- **Stage 2** — Load latest data → Ollama → confidence gate → Alpaca paper trade
- **Dashboard** — Read-only view of signals, trades, and snapshots

## Project structure

```
trading-system/
  docker-compose.yml      # Postgres + n8n + Adminer
  db/init.sql             # Database schema
  n8n/workflows/          # Importable workflow JSON
  web/                    # Next.js dashboard
  scripts/                # Install, verify, e2e tests
  .env.example            # Environment template
```

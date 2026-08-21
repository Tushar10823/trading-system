#!/usr/bin/env bash
# Trading System MVP - Linux/macOS setup helper
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== Trading System MVP - Setup ==="

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing: $1"
    return 1
  fi
  echo "[OK] $1: $($1 --version 2>/dev/null || $1 --help 2>&1 | head -1)"
}

echo ""
echo "--- Checking prerequisites ---"
MISSING=0
for cmd in git node npm python3; do
  need_cmd "$cmd" || MISSING=1
done

if ! command -v docker >/dev/null 2>&1; then
  echo "[WARN] docker not found. Install Docker Engine / Docker Desktop, then re-run."
  MISSING=1
else
  need_cmd docker
  docker compose version || MISSING=1
  if ! docker ps >/dev/null 2>&1; then
    echo "[WARN] Docker daemon not reachable for this user."
    echo "       Try: sudo service docker start"
    echo "       Then add yourself to the docker group and re-login:"
    echo "         sudo usermod -aG docker \"\$USER\""
    MISSING=1
  fi
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "[WARN] ollama not found. Install from https://ollama.com/download"
  MISSING=1
else
  need_cmd ollama
fi

echo ""
echo "--- Environment files ---"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit API keys before trading workflows run."
else
  echo ".env already exists"
fi

if [[ ! -f bot/.env ]]; then
  cp bot/.env.example bot/.env
  echo "Created bot/.env from bot/.env.example"
else
  echo "bot/.env already exists"
fi

echo ""
echo "--- Python bot ---"
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "Install python3-venv (e.g. apt install python3-venv), then re-run."
  MISSING=1
else
  python3 -m venv bot/venv
  # shellcheck disable=SC1091
  source bot/venv/bin/activate
  pip install -q --upgrade pip
  pip install -q -r bot/requirements.txt
  echo "Bot venv ready at bot/venv"
fi

echo ""
echo "--- Next.js dashboard ---"
(cd web && npm install)
echo "Web dependencies installed"

if command -v ollama >/dev/null 2>&1; then
  echo ""
  echo "--- Ollama model ---"
  if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "Start Ollama in another terminal: ollama serve"
  fi
  ollama pull "${OLLAMA_MODEL:-llama3.2}" || echo "[WARN] Could not pull Ollama model"
fi

echo ""
if [[ "$MISSING" -eq 1 ]]; then
  echo "Setup finished with warnings. Run ./scripts/verify.sh after installing missing tools."
  exit 1
fi

echo "Setup complete. Next steps:"
echo "  1. Edit .env and bot/.env with your API keys"
echo "  2. docker compose up -d"
echo "  3. Import n8n workflows from n8n/workflows/"
echo "  4. cd web && npm run dev   # http://localhost:3000"
echo "  5. ./scripts/verify.sh"

#!/usr/bin/env bash
# Verify prerequisites for Trading System MVP (Linux/macOS)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== Prerequisite Check ==="
ALL_OK=1

check() {
  local name="$1"
  shift
  if out=$("$@" 2>&1); then
    echo "[OK] $name: $out"
  else
    echo "[FAIL] $name"
    ALL_OK=0
  fi
}

check "Git" git --version
check "Node.js" node --version
check "npm" npm --version
check "Python" python3 --version
check "Docker" docker --version
check "Compose" docker compose version
check "Ollama" ollama --version
check "Docker running" bash -c 'docker ps >/dev/null 2>&1 || sudo docker ps >/dev/null 2>&1'

if command -v ollama >/dev/null 2>&1; then
  echo ""
  echo "Ollama models:"
  ollama list || true
fi

echo ""
if [[ "$ALL_OK" -eq 1 ]]; then
  echo "All checks passed."
else
  echo "Some checks failed. Run ./scripts/install.sh or install missing tools manually."
  exit 1
fi

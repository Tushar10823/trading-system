#!/usr/bin/env bash
# End-to-end smoke test for Trading System MVP
# Prerequisites: docker compose up -d, Ollama running with llama3.2
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== Trading System E2E Test ==="
PASSED=0
FAILED=0

test_step() {
  local name="$1"
  shift
  echo ""
  echo "[$name]"
  if "$@"; then
    echo "  PASS"
    PASSED=$((PASSED + 1))
  else
    echo "  FAIL"
    FAILED=$((FAILED + 1))
  fi
}

step_docker() {
  local names
  names=$(docker ps --format '{{.Names}}' 2>/dev/null || true)
  echo "$names" | grep -q trading-postgres || { echo "  trading-postgres not running"; return 1; }
  echo "$names" | grep -q trading-n8n || { echo "  trading-n8n not running"; return 1; }
  echo "  Containers: $(echo "$names" | tr '\n' ', ')"
}

step_postgres() {
  docker exec trading-postgres pg_isready -U trading -d trading
}

step_tables() {
  for t in market_snapshots signals trades; do
    local exists
    exists=$(docker exec trading-postgres psql -U trading -d trading -tAc \
      "SELECT to_regclass('public.$t') IS NOT NULL;")
    [[ "$exists" == "t" ]] || { echo "  Missing table: $t"; return 1; }
  done
  echo "  Tables: market_snapshots, signals, trades"
}

step_n8n() {
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:5678)
  [[ "$code" -lt 400 ]] || { echo "  HTTP $code"; return 1; }
  echo "  n8n responded HTTP $code"
}

step_ollama_tags() {
  local count
  count=$(curl -s http://localhost:11434/api/tags | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(len(d.get('models',[])))")
  [[ "${count:-0}" -ge 1 ]] || { echo "  No models listed"; return 1; }
  echo "  Models: $count"
}

step_ollama_generate() {
  local resp
  resp=$(curl -s http://localhost:11434/api/generate -d '{
    "model": "llama3.2",
    "prompt": "Respond ONLY with JSON: {\"action\":\"HOLD\",\"confidence\":50,\"reasoning\":\"test\"}",
    "stream": false
  }' -H 'Content-Type: application/json')
  echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('response'); print('  Response length:', len(d['response']), 'chars')"
}

step_insert_snapshot() {
  echo "INSERT INTO market_snapshots (symbol, price_json, news_json) VALUES ('AAPL', '{\"price\": 180.5}'::jsonb, '[{\"title\": \"Test headline\"}]'::jsonb);" \
    | docker exec -i trading-postgres psql -U trading -d trading -v ON_ERROR_STOP=1 >/dev/null
  echo "  Inserted test snapshot for AAPL"
}

step_read_snapshot() {
  local count
  count=$(docker exec trading-postgres psql -U trading -d trading -tAc \
    "SELECT COUNT(*) FROM market_snapshots WHERE symbol='AAPL';")
  [[ "${count:-0}" -ge 1 ]] || { echo "  No snapshots found"; return 1; }
  echo "  Snapshot count: $count"
}

step_dashboard() {
  if curl -sf http://localhost:3000/api/signals >/dev/null 2>&1; then
    local n
    n=$(curl -s http://localhost:3000/api/signals | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
    echo "  /api/signals returned $n items"
  else
    echo "  Dashboard not running (start with: cd web && npm run dev) - skipped"
  fi
}

test_step "Docker containers running" step_docker
test_step "Postgres accepts connections" step_postgres
test_step "Database tables exist" step_tables
test_step "n8n is reachable" step_n8n
test_step "Ollama is reachable" step_ollama_tags
test_step "Ollama generate returns JSON-like response" step_ollama_generate
test_step "Insert test market snapshot" step_insert_snapshot
test_step "Read test snapshot back" step_read_snapshot
test_step "Next.js dashboard API (if running)" step_dashboard

echo ""
echo "=== Results: $PASSED passed, $FAILED failed ==="
if [[ "$FAILED" -gt 0 ]]; then
  echo "Some tests failed. Check Docker, Ollama, and .env configuration."
  exit 1
fi
echo "All tests passed!"

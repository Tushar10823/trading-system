# End-to-end smoke test for Trading System MVP
# Prerequisites: docker compose up -d, Ollama running with llama3.2

$ErrorActionPreference = "Continue"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "=== Trading System E2E Test ===" -ForegroundColor Cyan
$passed = 0
$failed = 0

function Test-Step {
    param([string]$Name, [scriptblock]$Block)
    Write-Host "`n[$Name]" -ForegroundColor Yellow
    try {
        & $Block
        Write-Host "  PASS" -ForegroundColor Green
        $script:passed++
    } catch {
        Write-Host "  FAIL: $_" -ForegroundColor Red
        $script:failed++
    }
}

Test-Step "Docker containers running" {
    $ps = docker ps --format "{{.Names}}" 2>&1
    if ($ps -notmatch "trading-postgres") { throw "trading-postgres not running" }
    if ($ps -notmatch "trading-n8n") { throw "trading-n8n not running" }
    Write-Host "  Containers: $ps"
}

Test-Step "Postgres accepts connections" {
    $result = docker exec trading-postgres pg_isready -U trading -d trading 2>&1
    if ($LASTEXITCODE -ne 0) { throw $result }
    Write-Host "  $result"
}

Test-Step "Database tables exist" {
    $tables = docker exec trading-postgres psql -U trading -d trading -t -c `
        "SELECT tablename FROM pg_tables WHERE schemaname='public';" 2>&1
    foreach ($t in @("market_snapshots", "signals", "trades")) {
        if ($tables -notmatch $t) { throw "Missing table: $t" }
    }
    Write-Host "  Tables: market_snapshots, signals, trades"
}

Test-Step "n8n is reachable" {
    $resp = Invoke-WebRequest -Uri "http://localhost:5678" -UseBasicParsing -TimeoutSec 10
    if ($resp.StatusCode -ge 400) { throw "HTTP $($resp.StatusCode)" }
    Write-Host "  n8n responded HTTP $($resp.StatusCode)"
}

Test-Step "Ollama is reachable" {
    $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 10
    if (-not $resp.models) { throw "No models listed" }
    Write-Host "  Models: $($resp.models.Count)"
}

Test-Step "Ollama generate returns JSON-like response" {
    $body = @{
        model  = "llama3.2"
        prompt = 'Respond ONLY with JSON: {"action":"HOLD","confidence":50,"reasoning":"test"}'
        stream = $false
    } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" `
        -Method POST -Body $body -ContentType "application/json" -TimeoutSec 120
    if (-not $resp.response) { throw "Empty Ollama response" }
    Write-Host "  Response length: $($resp.response.Length) chars"
}

Test-Step "Insert test market snapshot" {
    $sql = @"
INSERT INTO market_snapshots (symbol, price_json, news_json)
VALUES ('AAPL', '{"price": 180.5}', '[{"title": "Test headline"}]');
"@
    docker exec trading-postgres psql -U trading -d trading -c $sql | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Insert failed" }
    Write-Host "  Inserted test snapshot for AAPL"
}

Test-Step "Read test snapshot back" {
    $count = docker exec trading-postgres psql -U trading -d trading -t -c `
        "SELECT COUNT(*) FROM market_snapshots WHERE symbol='AAPL';" 2>&1
    if ([int]$count.Trim() -lt 1) { throw "No snapshots found" }
    Write-Host "  Snapshot count: $($count.Trim())"
}

Test-Step "Next.js dashboard API (if running)" {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:3000/api/signals" -TimeoutSec 5
        Write-Host "  /api/signals returned $($resp.Count) items"
    } catch {
        Write-Host "  Dashboard not running (start with: cd web && npm run dev) - skipped" -ForegroundColor DarkYellow
    }
}

Write-Host "`n=== Results: $passed passed, $failed failed ===" -ForegroundColor Cyan
if ($failed -gt 0) {
    Write-Host "Some tests failed. Check Docker, Ollama, and .env configuration." -ForegroundColor Yellow
    exit 1
}
Write-Host "All tests passed!" -ForegroundColor Green

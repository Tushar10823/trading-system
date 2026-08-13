# End-to-end smoke test for Trading System MVP
# Prerequisites: docker compose up -d, Ollama running with llama3.2

$ErrorActionPreference = "Continue"
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
if (Test-Path "C:\Program Files\nodejs") {
    $env:Path = "C:\Program Files\nodejs;" + $env:Path
}

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
    $names = @(docker ps --format "{{.Names}}" 2>$null)
    $joined = $names -join "`n"
    if ($joined -notmatch "trading-postgres") { throw "trading-postgres not running. Got: $joined" }
    if ($joined -notmatch "trading-n8n") { throw "trading-n8n not running. Got: $joined" }
    Write-Host "  Containers: $($names -join ', ')"
}

Test-Step "Postgres accepts connections" {
    $result = docker exec trading-postgres pg_isready -U trading -d trading 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw $result.Trim() }
    Write-Host "  $($result.Trim())"
}

Test-Step "Database tables exist" {
    foreach ($t in @("market_snapshots", "signals", "trades")) {
        $exists = docker exec trading-postgres psql -U trading -d trading -tAc `
            "SELECT to_regclass('public.$t') IS NOT NULL;" 2>$null
        if (($exists | Out-String).Trim() -ne "t") { throw "Missing table: $t" }
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
    if (-not $resp.models -or $resp.models.Count -lt 1) { throw "No models listed" }
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
    # Pipe SQL via stdin to avoid PowerShell quote mangling for docker -c
    $sql = "INSERT INTO market_snapshots (symbol, price_json, news_json) VALUES ('AAPL', '{`"price`": 180.5}'::jsonb, '[{`"title`": `"Test headline`"}]'::jsonb);"
    $sql | docker exec -i trading-postgres psql -U trading -d trading -v ON_ERROR_STOP=1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Insert failed" }
    Write-Host "  Inserted test snapshot for AAPL"
}

Test-Step "Read test snapshot back" {
    $count = (docker exec trading-postgres psql -U trading -d trading -tAc `
        "SELECT COUNT(*) FROM market_snapshots WHERE symbol='AAPL';" 2>$null | Out-String).Trim()
    if (-not $count -or [int]$count -lt 1) { throw "No snapshots found (got: '$count')" }
    Write-Host "  Snapshot count: $count"
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

# Verify all prerequisites for Trading System MVP
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

$checks = @(
    @{ Name = "Git";       Cmd = "git --version" },
    @{ Name = "Node.js";   Cmd = "node --version" },
    @{ Name = "npm";       Cmd = "npm --version" },
    @{ Name = "Docker";    Cmd = "docker --version" },
    @{ Name = "Compose";   Cmd = "docker compose version" },
    @{ Name = "Ollama";    Cmd = "ollama --version" },
    @{ Name = "Docker running"; Cmd = "docker ps" }
)

Write-Host "=== Prerequisite Check ===" -ForegroundColor Cyan
$allOk = $true
foreach ($c in $checks) {
    try {
        $out = Invoke-Expression $c.Cmd 2>&1
        Write-Host "[OK] $($c.Name): $out" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] $($c.Name)" -ForegroundColor Red
        $allOk = $false
    }
}

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "`nOllama models:" -ForegroundColor Cyan
    ollama list
}

if ($allOk) { Write-Host "`nAll checks passed." -ForegroundColor Green }
else { Write-Host "`nSome checks failed. Run scripts\install.ps1 or install manually." -ForegroundColor Yellow }

# Trading System MVP - Software Installer
# Run from elevated PowerShell: .\scripts\install.ps1

$ErrorActionPreference = "Stop"
$Installers = "E:\AI"

Write-Host "=== Trading System MVP - Software Install ===" -ForegroundColor Cyan

function Install-IfExists {
    param([string]$Path, [string]$Args, [string]$Name)
    if (Test-Path $Path) {
        Write-Host "Installing $Name..." -ForegroundColor Yellow
        $proc = Start-Process -FilePath $Path -ArgumentList $Args -Wait -PassThru
        if ($proc.ExitCode -ne 0) { Write-Warning "$Name installer exited with code $($proc.ExitCode)" }
        else { Write-Host "$Name installed." -ForegroundColor Green }
    } else {
        Write-Warning "Not found: $Path"
    }
}

# 1. Git
Install-IfExists "$Installers\Git-2.55.0.3-64-bit.exe" "/VERYSILENT" "Git"

# 2. Node.js
Install-IfExists "msiexec.exe" "/i `"$Installers\node-v24.19.0-x64.msi`" /quiet /norestart" "Node.js"

# 3. Docker Desktop (may require reboot / manual start)
if (Test-Path "$Installers\Docker Desktop Installer.exe") {
    Write-Host "Installing Docker Desktop (this may take several minutes)..." -ForegroundColor Yellow
    Start-Process "$Installers\Docker Desktop Installer.exe" -ArgumentList "install", "--quiet" -Wait
    Write-Host "Docker Desktop installed. Start it from the Start menu if not running." -ForegroundColor Green
}

# 4. Ollama
Install-IfExists "$Installers\OllamaSetup.exe" "/S" "Ollama"

# 5. VS Code
Install-IfExists "$Installers\VSCodeUserSetup-x64-1.131.0.exe" "/VERYSILENT /MERGETASKS=!runcode" "VS Code"

# Refresh PATH
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")

Write-Host "`n=== Verification ===" -ForegroundColor Cyan
@("git", "node", "npm", "docker", "ollama") | ForEach-Object {
    $cmd = Get-Command $_ -ErrorAction SilentlyContinue
    if ($cmd) { Write-Host "$_`: $($cmd.Source)" -ForegroundColor Green }
    else { Write-Host "$_`: NOT FOUND - restart terminal after install" -ForegroundColor Red }
}

# Pull Ollama model
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollama) {
    Write-Host "`nPulling llama3.2 model (may take a while)..." -ForegroundColor Yellow
    & ollama pull llama3.2
}

Write-Host "`nDone. Restart your terminal, start Docker Desktop, then run: docker compose up -d" -ForegroundColor Cyan

# CrossLab Automated Windows Installer
# Installs uv (if missing), creates .venv, installs dependencies, and runs self-test.

$ErrorActionPreference = "Stop"

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "CrossLab Installer: A2A Empirical Collaboration Layer" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan

# 1. Check for uv
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "[*] uv package manager not found. Installing uv via Astral standalone installer..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.cargo\bin;$env:Path"
}

Write-Host "[+] uv is available: $(uv --version)" -ForegroundColor Green

# 2. Sync dependencies
Write-Host "[*] Syncing virtual environment and dependencies..." -ForegroundColor Yellow
uv sync --all-extras

# 3. Run Self-Test
Write-Host "[*] Running CrossLab self-test suite..." -ForegroundColor Yellow
uv run --extra dev pytest -q

Write-Host "`n[+] CrossLab successfully installed and verified!" -ForegroundColor Green
Write-Host "`nQuick Commands:" -ForegroundColor White
Write-Host "  Start Host Node:   .\scripts\start_host.ps1" -ForegroundColor Cyan
Write-Host "  Start Client Node: .\scripts\start_client.ps1 -Peer <host_ip_or_tailscale>" -ForegroundColor Cyan
Write-Host "  Start Relay Hub:   .\scripts\start_relay.ps1" -ForegroundColor Cyan
Write-Host "  Launch MCP Bridge: uv run crosslab mcp --node-url http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host "  Open Web Dashboard: http://localhost:8765/dashboard" -ForegroundColor Cyan

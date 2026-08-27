param (
    [int]$Port = 8080
)

Write-Host "[CrossLab] Starting Central Relay Hub on port $Port..." -ForegroundColor Green
uv run crosslab relay --port $Port

param (
    [int]$Port = 8765,
    [string]$Session = "fear3-debug"
)

Write-Host "[CrossLab] Starting Host Node on port $Port (Session: $Session)..." -ForegroundColor Green
Write-Host "[CrossLab] Web Dashboard available at http://localhost:$Port/dashboard" -ForegroundColor Cyan
uv run crosslab node --role host --port $Port --session $Session

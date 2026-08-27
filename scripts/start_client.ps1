param (
    [string]$Peer = "http://127.0.0.1:8765",
    [int]$Port = 8766,
    [string]$Session = "fear3-debug"
)

Write-Host "[CrossLab] Starting Client Node on port $Port, connecting to peer $Peer..." -ForegroundColor Green
Write-Host "[CrossLab] Web Dashboard available at http://localhost:$Port/dashboard" -ForegroundColor Cyan
uv run crosslab node --role client --port $Port --peer $Peer --session $Session

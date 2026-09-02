param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$OutDir = Join-Path $Root "desktop\src-tauri\binaries"
$DistDir = Join-Path $Root "dist"

Write-Host "[CrossLab] Building node sidecar with PyInstaller..." -ForegroundColor Cyan
Push-Location $Root
try {
    uv run pyinstaller packaging/crosslab-node.spec --noconfirm --clean
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $Built = Join-Path $DistDir "crosslab-node.exe"
    if (-not (Test-Path $Built)) {
        throw "Expected sidecar binary not found at $Built"
    }
    $Dest = Join-Path $OutDir "crosslab-node-$TargetTriple.exe"
    Copy-Item $Built $Dest -Force
    Write-Host "[CrossLab] Sidecar copied to $Dest" -ForegroundColor Green
}
finally {
    Pop-Location
}

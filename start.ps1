param([int]$Port = 7860)
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
Set-Location -LiteralPath $PSScriptRoot
$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) { throw "Please run setup.ps1 first." }
Write-Host "Voice Studio: http://127.0.0.1:$Port"
Write-Host "Press Ctrl+C to stop. Files are stored under data."
& $pythonExe run.py --port $Port

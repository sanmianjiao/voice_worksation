param([string]$PackageIndex = "https://pypi.org/simple")
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    py -3.10 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.10 is required. Install it and run setup.ps1 again." }
}
$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip --index-url $PackageIndex
if ($LASTEXITCODE -ne 0) { throw "pip installation failed" }
& $pythonExe -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw "PyTorch installation failed" }
& $pythonExe -m pip install -r requirements.lock.txt --index-url $PackageIndex
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
& $pythonExe scripts/download_models.py
if ($LASTEXITCODE -ne 0) { throw "Model download failed; rerun setup.ps1 to resume" }

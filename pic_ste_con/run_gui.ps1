Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host ".venv not found. Creating virtual environment..."
    python -m venv .venv
}

Write-Host "Installing/updating dependencies..."
.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "Starting GUI..."
.\.venv\Scripts\python.exe .\gui_main.py

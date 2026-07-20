# Uploads the Pico-side files (protocol.py + firmware/*.py) to the Pico via mpremote,
# reading straight from disk (never an editor buffer), then resets the Pico.
#
# The gui/ files run on the PC and are NOT uploaded.
#
# Usage:   .\push.ps1              (defaults to COM9)
#          .\push.ps1 -Port COM7   (if your Pico is on another port)
#
# Close Thonny (and any GUI/mpremote session) first so the port is free.

param([string]$Port = "COM9")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# make sure mpremote is available in the venv
& $py -c "import mpremote" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing mpremote into the venv..."
    & $py -m pip install mpremote
}

Write-Host "Uploading protocol.py + firmware/*.py to $Port ..."
& $py -m mpremote connect $Port fs cp protocol.py firmware/main.py firmware/tmc2208.py firmware/tmc2209.py firmware/state_store.py firmware/platform_axis.py firmware/gripper_axis.py firmware/demo_cycle.py :

Write-Host "Resetting the Pico..."
& $py -m mpremote connect $Port reset

Write-Host "Done - firmware uploaded and Pico reset."

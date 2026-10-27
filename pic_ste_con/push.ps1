# Uploads the Pico-side files (protocol.py + firmware/*.py) to the Pico via mpremote,
# reading straight from disk (never an editor buffer), then resets the Pico.
#
# The gui/ files run on the PC and are NOT uploaded.
#
# -Mode picks which standalone demo the Pico runs on boot (it rewrites the
# DEMO_MODE line in protocol.py before uploading): OUTSIDE_PICK (default, the
# 4-jaw outside pick) or TWO_JAW (the HOME<->MAIN shuttle - see push_2jaw.ps1).
#
# -NoAutoStart flashes a TUNING build: the demo does NOT run on boot, so the
# Pico just listens and you can drive OPEN/CLOSE and adjust StallGuard/torque
# from the GUI (see push_tune.ps1). Without it, the demo auto-runs on boot.
#
# Usage:   .\push.ps1                       (OUTSIDE_PICK, autostart, COM9)
#          .\push.ps1 -Port COM7            (OUTSIDE_PICK on COM7)
#          .\push.ps1 -Port COM7 -Mode TWO_JAW
#          .\push.ps1 -Port COM7 -NoAutoStart   (idle for GUI tuning)
#
# Close Thonny (and any GUI/mpremote session) first so the port is free.

param(
    [string]$Port = "COM7",
    [ValidateSet("OUTSIDE_PICK", "TWO_JAW")]
    [string]$Mode = "OUTSIDE_PICK",
    [switch]$NoAutoStart
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# Set the demo mode + autostart flag in protocol.py so the right build is
# flashed. The regexes match only the standalone assignment lines, not the
# DEMO_MODE_* name constants.
$auto = if ($NoAutoStart) { "False" } else { "True" }
Write-Host "Setting DEMO_MODE = $Mode, AUTO_START_ON_BOOT = $auto in protocol.py ..."
$proto = Join-Path $PSScriptRoot "protocol.py"
$text = Get-Content $proto -Raw
$text = $text -replace '(?m)^DEMO_MODE = "[A-Z_]+"', ('DEMO_MODE = "{0}"' -f $Mode)
$text = $text -replace '(?m)^AUTO_START_ON_BOOT = (True|False)', ('AUTO_START_ON_BOOT = {0}' -f $auto)
# Write UTF-8 WITHOUT a BOM. Set-Content -Encoding UTF8 (PS 5.1) prepends a BOM,
# and MicroPython can't parse a leading BOM - it fails to import protocol.py and
# main.py dies at boot. WriteAllText with UTF8Encoding($false) avoids that.
[System.IO.File]::WriteAllText($proto, $text, (New-Object System.Text.UTF8Encoding $false))

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

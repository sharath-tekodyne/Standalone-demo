# Flashes a TUNING build: the demo does NOT auto-run on boot, so you can connect
# the GUI and freely drive SM2 OPEN/CLOSE, jog, and adjust StallGuard threshold /
# torque / grip speed to find values that work - then note them down and flash a
# normal demo build (push.ps1 / push_2jaw.ps1) with those values baked in.
#
# Thin wrapper over push.ps1 -NoAutoStart.
#
# Usage:   .\push_tune.ps1             (defaults to COM9)
#          .\push_tune.ps1 -Port COM7  (if your Pico is on another port)
#
# Close Thonny (and any GUI/mpremote session) first so the port is free.

param([string]$Port = "COM7")

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "push.ps1") -Port $Port -NoAutoStart

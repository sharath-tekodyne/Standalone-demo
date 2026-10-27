# Flashes the 2-JAW demo (HOME <-> MAIN shuttle: home, go to MAIN, grab with
# force feedback, carry back to HOME, release fully, repeat - no REACH).
#
# Thin wrapper over push.ps1 -Mode TWO_JAW. To go back to the outside pick,
# just run push.ps1 (its default mode is OUTSIDE_PICK).
#
# Usage:   .\push_2jaw.ps1             (defaults to COM9)
#          .\push_2jaw.ps1 -Port COM7  (if your Pico is on another port)
#
# Close Thonny (and any GUI/mpremote session) first so the port is free.

param([string]$Port = "COM7")

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "push.ps1") -Port $Port -Mode TWO_JAW

# Gripper Demo - Setup Guide

## What this project uses

- Pico 2W running MicroPython
- SM1: TMC2208 in standalone mode (STEP/DIR/EN) - platform axis, homed by a
  limit switch (HOME) and jogged to a fixed step offset (MAIN)
- SM2: TMC2209 with UART-configured StallGuard (STEP/DIR/EN/DIAG + UART) -
  gripper axis (OPEN/CLOSED, with grip-force feedback)
- A limit switch (SM1 home) and a push-button (latching pause/resume, and
  start on first press)
- Desktop Python GUI over USB serial (optional - used for calibration and
  monitoring; the demo runs standalone from the button once set up)

See [README.md](README.md) for the full file layout and protocol reference.

## 1) Flash and prepare the Pico in Thonny

1. Open Thonny and select MicroPython (Raspberry Pi Pico).
2. Save `protocol.py` (repo root) to the Pico filesystem root.
3. Save every file under `firmware/` to the Pico filesystem root - flat,
   not in a subfolder:
   - `tmc2208.py`
   - `tmc2209.py`
   - `state_store.py`
   - `platform_axis.py`
   - `gripper_axis.py`
   - `demo_cycle.py`
   - `calibrate_main_steps.py`
   - `main.py`
4. Power-cycle the Pico (or use Thonny's Stop/Restart) and wait for the
   `READY main.py` line in the Shell.

`main.py` auto-starts on every Pico power-up/reset - no need to run it from
Thonny each time. Nothing moves on its own after a reboot (see "Safety" in
[README.md](README.md)): the first push-button press homes and starts the
cycle, and the button then toggles pause/resume.

## 2) Wire pins (Pico -> drivers)

| Signal                | GPIO |
|-----------------------|------|
| SM1 STEP (3-pin JST)   | GP19 |
| SM1 DIR                | GP20 |
| SM1 EN                 | GP18 |
| SM1 HOME limit switch  | GP21 |
| SM2 STEP (6-pin JST)   | GP2  |
| SM2 DIR                | GP3  |
| SM2 EN                 | GP4  |
| SM2 DIAG (StallGuard)  | GP5  |
| SM2 UART0 TX           | GP0  |
| SM2 UART0 RX           | GP1  |
| Pause push-button      | GP22 |

These live in `protocol.py` as named constants - if you rewire, edit them
there once and both sides of the serial link stay in sync.

Wire the limit switch and the push-button each between their GPIO and GND;
the firmware uses the internal pull-up, so they read as actuated when pulled
low. For normally-closed switches or a button to 3V3, set
`HOME_SWITCH_ACTIVE_LOW` / `PAUSE_BUTTON_ACTIVE_LOW = False` in `protocol.py`.
The switch must sit on the CW side of travel, since homing drives CW into it.

## 3) Start the desktop GUI

From PowerShell in this folder:

```powershell
.\run_gui.ps1
```

This will:
- ensure `.venv` exists,
- install requirements,
- launch `gui_main.py`.

Manual equivalent:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\gui_main.py
```

## 4) Measure MAIN once (before the first demo run)

`MAIN` is a fixed step offset from HOME, measured once. **The easiest way is
in the GUI** (see step 6): the **Step-by-Step** tab has a "Calibrate MAIN"
box - jog SM1 to HOME, click "Start recording", jog out to MAIN, click "Save
as MAIN". That persists the count on the Pico's flash, no file edit.

If you prefer not to use the GUI, do it in Thonny instead:

1. In Thonny, **Run** `calibrate_main_steps.py` (do not rename it to
   main.py). It homes SM1 CW into the limit switch, then prompts you to jog
   toward MAIN.
2. Type a step count (e.g. `200`) to jog CW, or a negative number to back
   up; it prints the running total after each jog.
3. When the platform is exactly at MAIN, type `q`. It prints the
   HOME -> MAIN step count.
4. Paste that number into `SM1_MAIN_STEPS` in `protocol.py` and re-upload
   `protocol.py` to the Pico.

## 5) Calibrate the gripper

The demo also needs SM2's closed limit (the **Calibration** tab shows
what's still missing):

1. **Manual Control** tab: jog SM2's jaws fully open, then in
   **Calibration** click "Mark OPEN here".
2. Jog SM2's jaws to fully closed with nothing between them (this defines
   the "nothing gripped" travel limit that StallGuard needs), click
   "Mark CLOSED here".
3. Click "Refresh Calibration Status" and confirm `MAIN` and `CLOSED` are
   set.

## 6) Bring it up step by step, then run the full demo

Before trusting the continuous loop, use the **Step-by-Step** tab to validate
each action once:

1. In **Prerequisites**, click "Enable SM1" and "Enable SM2" (and "Stop demo"
   if it is running). Watch the SM1/SM2/UART/Demo indicators.
2. In the **step runner**, click **Run** on step 1, watch the result, and
   physically confirm the motion before clicking **OK** (or **Fail**). Work
   down the list one step at a time. Any error - or a Pico that never
   replies - shows inline and in the red error bar, with the exact reason.

Then run the whole thing: either **press the physical button** (first press
homes and starts), or use the **Demo Cycle** tab and click **Start**. The
cycle homes to the switch, then jogs HOME <-> MAIN opening/closing the
gripper at HOME. Press the button again (or click **Pause**) to freeze in
place; press again (or **Resume**) to continue the exact same phase. If the
demo hits a fault (e.g. homing can't find the switch) it auto-pauses with a
"needs attention" banner - check the console, fix it, and Resume.

## Notes

- Keep Thonny's serial shell disconnected while the GUI is connected to the
  same COM port.
- Since `main.py` auto-runs, connecting Thonny will show it already busy in
  the Shell - click Stop (or Ctrl+C) to interrupt it and get a REPL prompt
  back for debugging, then Run/reset to restart it.
- Baud rate is 115200 on both sides.
- If the gripper grips too early/late, adjust the StallGuard threshold in
  **Manual Control** (SM2 section) - lower is more sensitive.
- The previous single-motor implementation is kept under `legacy/` for
  reference; it is not used by the current bridge or GUI.

## Troubleshooting

- No port listed: unplug/reconnect the Pico, click Refresh in the
  Connection bar.
- Connect fails: close Thonny or disconnect its Pico shell/serial session
  first.
- `pyserial missing`: run `pip install pyserial` inside `.venv`.
- SM2 shows "NOT WIRED / CHECK UART" in Manual Control: the TMC2209 UART
  link failed at boot - check TX/RX wiring and that the driver is powered.
- Homing runs forever / errors "limit switch never tripped": the switch
  isn't reaching the pin, is on the wrong (ACW) side of travel, or the
  polarity is inverted - verify wiring, that it sits CW-ward of the
  carriage, and `HOME_SWITCH_ACTIVE_LOW`. The live "Home switch" indicator
  (Calibration/Demo tabs) should read TRIGGERED when you press the switch
  by hand.
- The button does nothing / demo won't start: check the live "Pause button"
  indicator flips PRESSED when held; if not, check `PAUSE_BUTTON_PIN` and
  `PAUSE_BUTTON_ACTIVE_LOW`. Remember MAIN and CLOSED must be set first, or
  the first press raises a "calibrate before starting" error in the console.
- `MAIN (steps)` shows "not set": you haven't set `SM1_MAIN_STEPS` in
  `protocol.py` (or set it and didn't re-upload `protocol.py`). Re-run
  `calibrate_main_steps.py` if you don't have the number.
- `AttributeError: 'module' object has no attribute 'PHASE_...'` (or any
  other `AttributeError` mentioning `protocol`): the Pico is running an
  older `protocol.py` than the rest of `firmware/`. Re-upload `protocol.py`
  (and, when in doubt, every file under `firmware/`) from Thonny and
  power-cycle. Since this project is under active development, get in the
  habit of re-uploading the whole set after pulling any code change rather
  than assuming a single file changed.
- Jog/Goto/Open/Close refuses with "SM1/SM2 is disabled": that axis's
  Enable/Disable state is now a real latch (see README "Using the GUI") -
  click Enable for that axis first. Check the ENABLED/DISABLED indicator in
  Manual Control if it's unclear which state it's in.
- Motion doesn't happen: use **Diagnostics** -> Status/Stats and read the
  `DBG`/`ERR` lines in the console. With bridge debug on, every chunk of a
  move logs its requested/completed/stalled/position - if a move keeps
  stalling at the same position every time (rather than progressing
  further each attempt), that is almost always a real mechanical limit or a
  StallGuard threshold that's too sensitive, not a software bug - see the
  `SM2 SET STALLTHRESHOLD` control.
- Need a session trace: check the newest file under `logs/`.

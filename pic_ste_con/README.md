# 2-Jaw Gripper Demo - Pico 2W Controller

A Pico 2W running MicroPython drives two stepper axes as a standalone,
persisted, resumable jog demo. A Windows desktop GUI (over USB serial) is
optional - it is used for calibration and monitoring, but the demo runs
without a PC once set up, controlled by a physical push-button.

- **SM1 - platform axis** (TMC2208, STEP/DIR/EN only): jogs between two
  positions. **HOME** is found physically by driving CW into a **limit
  switch**; **MAIN** is a fixed step offset from HOME (measured once with
  `firmware/calibrate_main_steps.py` and stored in `protocol.SM1_MAIN_STEPS`).
- **SM2 - gripper axis** (TMC2209, STEP/DIR/EN + UART-configured StallGuard):
  opens and closes the jaws at HOME. StallGuard's DIAG pin is the "force
  feedback" - if the jaws meet resistance before the fully-closed position,
  that resistance stops the close early (a successful grip).

The demo loop (all gripper actions happen at HOME; MAIN is the far travel
point):

    home to the limit switch
    loop:
      open gripper (at HOME)
      move HOME -> MAIN
      move MAIN -> HOME
      close gripper (at HOME)
      move HOME -> MAIN
      move MAIN -> HOME
      open gripper (at HOME)
      close gripper (at HOME)   -> cycle count += 1
      repeat

A physical **push-button** is a latching toggle: press to pause (the axes
freeze in place with their exact phase/position remembered), press again to
resume from that point. The very first press homes and starts the cycle.
The GUI's Start/Pause/Resume buttons drive the same paths.

## Repository layout

```
protocol.py             Shared command names, phase names, pin map, and
                         tuning defaults - imported by BOTH the Pico
                         firmware and the desktop GUI, so they can't drift
                         out of sync with each other.

firmware/                Everything that runs on the Pico (MicroPython).
  tmc2208.py              SM1 driver (STEP/DIR/EN, speed/torque presets).
  tmc2209.py              SM2 driver (STEP/DIR/EN + UART StallGuard config).
  state_store.py          Atomic JSON persistence on the Pico's flash.
  platform_axis.py        SM1 wrapper: limit-switch homing + chunked move_to().
  gripper_axis.py         SM2 wrapper: open/close + grip verification.
  demo_cycle.py           The persisted demo loop state machine.
  calibrate_main_steps.py Run-once helper: home, jog to MAIN, print step count.
  main.py                 Serial command dispatcher + main loop. Copy this
                           (plus everything else in firmware/ and protocol.py)
                           onto the Pico. Named main.py so MicroPython
                           auto-runs it on every power-up/reset.

desktop/                  The Windows GUI (regular CPython + ttkbootstrap).
  serial_client.py         Non-blocking serial port wrapper.
  session_logger.py        Timestamped Markdown session logs (see logs/).
  app.py                   Main window: connection handling, status parsing.
  panels/
    connection_panel.py     Port selection, connect/disconnect.
    manual_panel.py          Manual jog/test controls for SM1 and SM2.
    calibration_panel.py     One-time HOME/A/B and OPEN/CLOSED calibration.
    demo_panel.py            Start/Pause/Resume/Reset + live cycle status.
    diagnostics_panel.py     Raw command entry, debug toggle, self test.

gui_main.py               Desktop entry point: `python gui_main.py`.
run_gui.ps1               One-command Windows launcher.
requirements.txt          Desktop Python dependencies.
legacy/                   The previous single-motor implementation, kept
                           for reference.
logs/                     Timestamped GUI session reports.
```

## Wiring (Pico 2W)

| Signal                | GPIO   |
|-----------------------|--------|
| SM1 STEP (3-pin JST)  | GP19   |
| SM1 DIR               | GP20   |
| SM1 EN                | GP18   |
| SM1 HOME limit switch | GP21   |
| SM2 STEP (6-pin JST)  | GP2    |
| SM2 DIR               | GP3    |
| SM2 EN                | GP4    |
| SM2 DIAG (StallGuard) | GP5    |
| SM2 UART0 TX          | GP0    |
| SM2 UART0 RX          | GP1    |
| Pause push-button     | GP22   |

All of these are defined in one place, [`protocol.py`](protocol.py) - change
the constants there if you wire it differently, so both the Pico and the
GUI's understanding of the pinout stay consistent.

EN is active-low on both driver modules. Power the drivers/motors
separately as required by your hardware.

The limit switch and push-button are each wired between their GPIO and GND
and use the RP2040 internal pull-up, so they read as actuated when the pin
goes low. If you use normally-closed contacts or wire a button to 3V3
instead, flip `HOME_SWITCH_ACTIVE_LOW` / `PAUSE_BUTTON_ACTIVE_LOW` in
`protocol.py` - no code change needed.

## First-time setup

1. Open Thonny and select the MicroPython interpreter for the Pico.
2. Copy `protocol.py` and every file under `firmware/` to the Pico's
   filesystem root (flat, no subfolder - Thonny's file browser lets you
   multi-select and upload). `firmware/main.py` must land as `main.py` at
   the Pico's root - that name is what MicroPython auto-runs on boot.
3. **Measure MAIN once.** Two ways, pick either:
   - *In the GUI* (easiest): the **Step-by-Step** tab has a "Calibrate MAIN"
     box - jog SM1 to HOME, click "Start recording", jog out to MAIN, click
     "Save as MAIN". The step count is stored on the Pico's flash (no file
     edit needed).
   - *In Thonny*: run `firmware/calibrate_main_steps.py` (Run, don't rename
     it to main.py); it homes, lets you jog to MAIN, and prints the count -
     paste that into `SM1_MAIN_STEPS` in `protocol.py` and re-upload it.
4. Power-cycle the Pico (or click Thonny's Stop/Restart) and confirm you
   see `READY main.py` in the Shell.
5. Close Thonny, or switch its interpreter away from the Pico, before
   connecting the desktop GUI - only one program can own the serial port.

Because it auto-runs, the demo is always live and listening after any
power-up - but nothing moves on boot (see "Safety" below). The **first**
push-button press homes and starts the cycle; after that the button toggles
pause/resume. (You can instead start/resume from the GUI, or set
`AUTO_START_ON_BOOT = True` in `protocol.py` for a hands-off rig that homes
and runs the instant it powers on.)

## Desktop GUI setup

```powershell
.\run_gui.ps1
```

This creates `.venv` if needed, installs `requirements.txt`, and launches
the GUI (`gui_main.py`). See [SETUP.md](SETUP.md) for the manual steps and
[GUI walkthrough](#using-the-gui) below.

## Using the GUI

The window has a permanent **Connection** bar plus five tabs:

1. **Manual Control** - jog SM1/SM2 by hand, enable/disable, set
   speed/torque (preset or an exact manual speed in microseconds per step),
   home SM1 to the switch, drive SM2 open/closed, or send either axis to an
   exact step count. Each axis shows a live ENABLED/DISABLED indicator -
   Stop/Disable now actually holds (no further motion is accepted) until you
   click Enable again, and also pauses the demo if it was running.
   **Freedrive** de-energizes an axis so you can move it by hand; the axis
   then needs to be re-homed/re-calibrated since manual movement isn't
   tracked. This whole tab is blocked by the bridge while the demo is running.
2. **Calibration** - Home SM1 to the limit switch, confirm `MAIN (steps)`
   is set, and mark SM2 OPEN/CLOSED. Once MAIN and CLOSED are set the demo
   can start; see the in-tab instructions.
3. **Step-by-Step** - the recommended tool for bringing a new rig up. It
   has a **Calibrate MAIN** box (jog SM1 to HOME, "Start recording", jog to
   MAIN, "Save as MAIN" - the count is persisted on the Pico; or type a known
   value into "Set MAIN steps") and a **step
   runner** that breaks the demo cycle into its individual actions (home,
   open, move to MAIN, move to HOME, close, ...). Run each action on its own,
   read the exact OK/ERR result, and mark it working or failed before moving
   on. A pre-flight check blocks a step with a plain-English reason
   (not connected, axis disabled, demo still running, gripper UART down) and
   every command is timed out if the Pico never replies.
4. **Demo Cycle** - Start / Pause (the interrupt) / Resume / Reset, plus a
   live view of the current phase, gripper state, positions, and the live
   home-switch and push-button states. If the demo hits a fault (for
   example homing can't find the switch) it auto-pauses and a "needs
   attention" banner appears - check the console, fix it, and click Resume.
5. **Diagnostics** - raw command entry, Ping/Version/Help/Stats, bridge
   debug logging, and a short self-test sequence.

All raw bridge traffic is mirrored into the **Pico Console** pane and into
a timestamped report under `logs/`.

## Command protocol

See `protocol.py` for the authoritative list of command/phase names, and
`firmware/main.py`'s `help_line()` (or send `HELP` once connected)
for the exact syntax. Summary:

- `PING`, `VERSION`, `HELP`, `STATUS`, `STATS`, `RESETSTATS`, `DEBUG ON|OFF`, `ESTOP`
- `SM1 ENABLE|DISABLE|STOP|FREEDRIVE`, `SM1 SET SPEED|TORQUE LOW|MEDIUM|HIGH`,
  `SM1 SET SPEEDUS <us>|AUTO`, `SM1 HOME`, `SM1 JOG CW|ACW <steps>`,
  `SM1 GOTO HOME|MAIN`, `SM1 GOTO STEPS <n>`, `SM1 MARK HOME`
- `SM2 ENABLE|DISABLE|STOP|FREEDRIVE`, `SM2 SET SPEED|TORQUE LOW|MEDIUM|HIGH`,
  `SM2 SET SPEEDUS <us>|AUTO`, `SM2 SET STALLTHRESHOLD <0-255>`,
  `SM2 JOG CW|ACW <steps>`, `SM2 OPEN`, `SM2 CLOSE`, `SM2 GOTO STEPS <n>`,
  `SM2 MARK OPEN|CLOSED`
- `DEMO START|PAUSE|RESUME|RESET`
- `CAL STATUS|CLEAR`

`ENABLE`/`DISABLE`/`STOP`/`FREEDRIVE` are latched in `state["sm1_enabled"]`/
`state["sm2_enabled"]` (reported in `STATUS`) - `JOG`/`GOTO`/`OPEN`/`CLOSE`
all refuse to run unless that axis is currently enabled, so Stop genuinely
stops further motion rather than being silently overridden by the next
motion command's own auto-enable.

## How resumability works

Every phase transition, every completed motion chunk, and every calibration
change is written to `state.json` on the Pico's flash (`firmware/state_store.py`,
atomic write via a temp file + rename). That means:

- Clicking **Pause** always leaves the system in a well-defined phase and
  position; **Resume** continues that exact phase rather than restarting
  the cycle.
- A Pico power cycle mid-demo reloads the same state on boot (`main.py`
  auto-runs, so this includes an unattended power blip, not just a
  deliberate restart), so the demo can be resumed. Position tracking away
  from HOME is open-loop step counting (no encoder), but every re-home
  drives back into the limit switch and re-zeroes, so drift is cancelled
  each cycle rather than accumulating.

## Safety

`main.py` always comes up with `demo_running` forced to `False` on boot,
even if it was `True` (mid-cycle) in the last saved state - auto-run must
never resume physical motion by itself. After any power cycle an operator
has to press the physical button (or click **Resume**/**Start** in the GUI),
exactly like after a manual Pause. (Setting `AUTO_START_ON_BOOT = True`
opts out of this and homes+runs on boot - use only on a rig where
unattended startup motion is safe.)

`ESTOP` (also sent automatically when the GUI window closes) disables both
drivers immediately. `SM1/SM2 STOP` disable just that axis. The system can
only sense position through the open-loop step count, the HOME limit
switch, and StallGuard.

## Future work

- Periodic re-homing mid-cycle (a `home()` touch every N cycles) if you
  want to cancel open-loop drift even more aggressively than the once-per-
  cycle return to HOME already does.
- An encoder on SM1 if true closed-loop position feedback is ever needed.

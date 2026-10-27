"""Shared constants for the gripper demo.

This file is imported on BOTH sides of the USB serial link:
- on the Pico (MicroPython), by everything under firmware/
- on the desktop (CPython), by the gui/ package

Keeping the command names, phase names, and default pin/tuning values in one
place means the two sides can never silently drift out of sync with each
other. Because MicroPython has to load this file too, avoid anything CPython
-only (f-strings, type hints, dataclasses, pathlib, etc.) below.

Do not use f-strings, dataclasses, pathlib, or type hints in this file
so it stays MicroPython-safe.
"""

# --------------------------------------------------------------------------
# Wiring (Pico 2W GPIO numbers). Change here if you wire it differently -
# both firmware and GUI documentation read from this single source.
# --------------------------------------------------------------------------

SM1_STEP_PIN = 19   # platform axis (TMC2208) - unchanged from the original single-motor build
SM1_DIR_PIN = 20
SM1_EN_PIN = 18
# Platform motor coils were soldered reversed on this board, so CW/ACW came out
# swapped. Invert the DIR pin so logical CW = physical CW again. NOTE: this
# affects EVERY board running this firmware - set False for a board wired the
# normal way (or fix that board by swapping one coil's two wires instead).
SM1_INVERT_DIR = True

SM2_STEP_PIN = 2   # gripper axis (TMC2209) - wired via a 6-pin JST
SM2_DIR_PIN = 3
SM2_EN_PIN = 4
SM2_DIAG_PIN = 5   # StallGuard output, used as the force-feedback grip sensor
SM2_UART_ID = 0    # GP0/GP1 are UART0 pins on the RP2040 (not UART1)
SM2_UART_TX_PIN = 0
SM2_UART_RX_PIN = 1

# Gripper motor coils were soldered reversed on this board too, so its CW/ACW
# came out swapped. Invert the DIR pin so logical CW = physical CW again
# (open-loop step tracking is unchanged). Set False for a normally-wired board.
SM2_INVERT_DIR = True

# SM1 HOME limit switch and the physical pause button. Both are wired between
# their GPIO and GND and use the RP2040 internal pull-up, so they read 0 when
# actuated (active-low). Flip the *_ACTIVE_LOW flags if you wire them the
# other way round (e.g. a normally-closed switch, or a button to 3V3).
SM1_HOME_SWITCH_PIN = 21
PAUSE_BUTTON_PIN = 22
HOME_SWITCH_ACTIVE_LOW = True
PAUSE_BUTTON_ACTIVE_LOW = True

# --------------------------------------------------------------------------
# Named platform positions (SM1). HOME is step position 0 - it is found
# physically by driving CW into the limit switch (not marked by hand). MAIN
# is a fixed step offset from HOME; that offset is measured once with
# firmware/calibrate_main_steps.py and pasted into SM1_MAIN_STEPS below.
# --------------------------------------------------------------------------

POSITION_HOME = "HOME"
POSITION_MAIN = "MAIN"

# Distance from HOME to MAIN, as a POSITIVE magnitude of steps. MAIN is always
# reached by moving ACW (away from the switch); HOME is CW back into the switch.
# The firmware applies that direction for you, so just put the step count you
# measured here (no sign to worry about). Left at 0 the platform won't travel.
SM1_MAIN_STEPS = 4500

# Standalone outside-pick demo positions (SM1 ABSOLUTE step targets from HOME=0).
# Negative = ACW, away from the limit switch. These are the far pick point (MAIN)
# and the final reach point the carriage ends each cycle on (REACH). Tune to the
# rig - HOME is always step 0 (found by the switch).
SM1_MAIN_ABS = -10000
SM1_REACH_ABS = -7000

# SM1 platform speed during the demo, as the step half-period in microseconds
# (smaller = faster). Applied as the SM1 speed override when the demo starts.
# 450 us is the HIGH preset's rate; drop it further only if the motor keeps up
# without skipping steps, raise it if it stalls/loses position on the long moves.
SM1_DEMO_SPEED_US = 450

# --------------------------------------------------------------------------
# Gripper jaw states (SM2)
# --------------------------------------------------------------------------

GRIPPER_OPEN = "OPEN"
GRIPPER_CLOSED = "CLOSED"
GRIPPER_UNKNOWN = "UNKNOWN"

# --------------------------------------------------------------------------
# Demo cycle phases - the standalone OUTSIDE pick (CLOSE grabs with force
# feedback, OPEN releases fully). On boot the rig RELEASES then HOMES ONCE
# (priming), then loops the 6-phase body. NEXT_PHASE is the full linear path -
# no branch (a CLOSE that reaches fully-shut with no object is normal here).
#
# RELEASE runs first so a gripper that powered off clamped on an object opens
# and lets go BEFORE homing - a clamped jaw can otherwise stop SM1 from ever
# reaching the switch. Opening when already open is a no-op, so when nothing is
# held RELEASE does nothing and the rig just homes.
#
# Cycle:
#   RELEASE                open jaws / drop any held object   (once)
#   -> HOMING              find HOME on the limit switch      (once)
#   -> OUT_TO_MAIN         move to MAIN (jaws open)      <-- loop body starts
#   -> CLOSE_GRAB          CLOSE on the object (force feedback)
#   -> BACK_TO_HOME        carry to HOME (step 0)
#   -> OUT_TO_MAIN_2       carry back out to MAIN
#   -> OPEN_RELEASE        OPEN fully to release
#   -> TO_REACH            move to REACH  (cycle_count += 1)
#   -> (back to OUT_TO_MAIN)
# --------------------------------------------------------------------------

PHASE_RELEASE = "RELEASE"
PHASE_HOMING = "HOMING"
PHASE_OUT_TO_MAIN = "OUT_TO_MAIN"
PHASE_CLOSE_GRAB = "CLOSE_GRAB"
PHASE_BACK_TO_HOME = "BACK_TO_HOME"
PHASE_OUT_TO_MAIN_2 = "OUT_TO_MAIN_2"
PHASE_OPEN_RELEASE = "OPEN_RELEASE"
PHASE_TO_REACH = "TO_REACH"

# The phase every fresh start/boot begins at (see DemoCycle.start).
FIRST_PHASE = PHASE_RELEASE

# Two standalone demos share this one firmware; DEMO_MODE picks which runs on
# boot. Flip it with the push scripts - push.ps1 flashes OUTSIDE_PICK,
# push_2jaw.ps1 flashes TWO_JAW - or edit this line and re-push. Both start the
# same way (RELEASE -> HOMING); they differ only in the loop body below.
DEMO_MODE_OUTSIDE_PICK = "OUTSIDE_PICK"
DEMO_MODE_TWO_JAW = "TWO_JAW"
DEMO_MODE = "OUTSIDE_PICK"

# OUTSIDE pick: grab at MAIN, carry to HOME, back out to MAIN, release, park at
# REACH, then loop.
NEXT_PHASE_OUTSIDE_PICK = {
    PHASE_RELEASE: PHASE_HOMING,
    PHASE_HOMING: PHASE_OUT_TO_MAIN,
    PHASE_OUT_TO_MAIN: PHASE_CLOSE_GRAB,
    PHASE_CLOSE_GRAB: PHASE_BACK_TO_HOME,
    PHASE_BACK_TO_HOME: PHASE_OUT_TO_MAIN_2,
    PHASE_OUT_TO_MAIN_2: PHASE_OPEN_RELEASE,
    PHASE_OPEN_RELEASE: PHASE_TO_REACH,
    PHASE_TO_REACH: PHASE_OUT_TO_MAIN,  # steady-state loop point (skips priming)
}

# TWO-JAW: simple pick-and-place shuttling HOME <-> MAIN only (no REACH). Go out
# to MAIN, grab (force feedback), carry back to HOME, release fully, then loop.
NEXT_PHASE_TWO_JAW = {
    PHASE_RELEASE: PHASE_HOMING,
    PHASE_HOMING: PHASE_OUT_TO_MAIN,
    PHASE_OUT_TO_MAIN: PHASE_CLOSE_GRAB,
    PHASE_CLOSE_GRAB: PHASE_BACK_TO_HOME,
    PHASE_BACK_TO_HOME: PHASE_OPEN_RELEASE,
    PHASE_OPEN_RELEASE: PHASE_OUT_TO_MAIN,  # steady-state loop point (skips priming)
}

if DEMO_MODE == DEMO_MODE_TWO_JAW:
    NEXT_PHASE = NEXT_PHASE_TWO_JAW
    CYCLE_END_PHASE = PHASE_OPEN_RELEASE   # one carry-and-release = one cycle
else:
    NEXT_PHASE = NEXT_PHASE_OUTSIDE_PICK
    CYCLE_END_PHASE = PHASE_TO_REACH       # reaching REACH = one cycle

# --------------------------------------------------------------------------
# Tunable defaults. All are changeable at runtime over serial; these are
# just the values loaded fresh the first time (before any calibration file
# exists).
# --------------------------------------------------------------------------

DEFAULT_SPEED = "MEDIUM"
DEFAULT_TORQUE = "MEDIUM"
DEFAULT_STALLGUARD_THRESHOLD = 75     # 0-255; working reference boot value (DIAG trips when load reading drops below threshold*2)
DEFAULT_CHUNK_STEPS = 100             # motion is chunked this small so PAUSE/interrupt is responsive
SPEED_LEVELS = ("LOW", "MEDIUM", "HIGH")
TORQUE_LEVELS = ("LOW", "MEDIUM", "HIGH")

# --------------------------------------------------------------------------
# Homing (SM1 CW into the limit switch) and physical push-button tuning.
# --------------------------------------------------------------------------

HOMING_SPEED_US = 900          # half-period per step on the fast approach
HOMING_SLOW_US = 1600          # slower half-period on the re-approach for a repeatable zero
HOMING_MAX_STEPS = 200000      # safety cap: give up (error) if the switch never trips
HOMING_BACKOFF_STEPS = 400     # after first contact, back off this far then re-approach slowly
# Ease SM1 into motion instead of commanding full homing speed from a standstill
# (a cold start straight at HOMING_SPEED_US can stall and never reach the switch).
# The approach starts at HOMING_START_US and accelerates to the target over the
# first HOMING_RAMP_STEPS steps. Raise HOMING_START_US if it still stalls at t=0.
HOMING_START_US = 2000
HOMING_RAMP_STEPS = 300

BUTTON_DEBOUNCE_MS = 30        # a button reading must be stable this long to count

# Gripper CLOSE/open-to-stop step half-period (us). 600 matches the working
# reference system's normal-move SPEED_US at 1/8 microstepping (see
# SM2_MICROSTEPS) - that combination is what actually produces a StallGuard
# signal. (The old 100 was a guess from when microstepping was left fine and the
# shaft crawled.) If detection is marginal, try 400 (their NUDGE_SPEED_US).
SM2_GRIP_SPEED_US = 600

# SM2 microstep resolution (per full step) set over UART at boot. StallGuard4
# gives no usable load signal when the shaft turns too slowly; the TMC2209
# power-on default is fine microstepping (very slow shaft at these pulse rates),
# so we force a coarser value here for enough velocity to sense a stall. NOTE:
# changing this rescales SM2 step counts - re-mark CLOSED after changing it.
SM2_MICROSTEPS = 8

# Grip mode.
#   False = POSITION-BASED (current): CLOSE drives the jaws open-loop to the
#           calibrated CLOSED step position and stops there, holding with motor
#           current. No StallGuard, no detection - you set CLOSED to the jaw
#           position that clamps the object, and every close returns to it.
#           Repeatable because RELEASE re-homes the jaws to the open hard stop
#           (StallGuard, which works in the open direction) each boot.
#   True  = FORCE-FEEDBACK: close until StallGuard trips on the object.
# Set False here because StallGuard would not trip reliably on the close stroke
# on this rig. CLOSED persists in state.json across reboots.
GRIPPER_FORCE_FEEDBACK = False
SM2_GRIP_OVERTRAVEL = 300   # steps commanded past fully-shut to guarantee a jam
SM2_GRIP_MARGIN = 60        # stalling this far before fully-shut = a real grip

# StallGuard threshold the demo applies on every start/boot (the demo owns this
# so the grip behaves the same standalone, regardless of what's in state.json).
# 75 = the working reference system's boot SG_THRESHOLD. Its calibrated profiles
# span 30 (firm/hard-stop) .. 75 (light). Tune from the SGREAD readings if the
# grip trips on nothing or closes right through the object.
SM2_DEMO_STALLGUARD_THRESHOLD = 75

# Grip current the demo applies on every start/boot, as a torque preset. MEDIUM
# = IRUN 16, which matches the working reference system's boot current. LOW/
# MEDIUM/HIGH. Raise if the grip is too weak to hold the object; lower if
# StallGuard won't register the load.
SM2_DEMO_TORQUE = "MEDIUM"

# Force-feedback OPEN (the 4-jaw demo, step 8): the jaws EXPAND (open direction)
# to grip a test tube from the inside, watching StallGuard, and stop the instant
# they meet the tube wall. Unlike CLOSE there's no fixed cap to jam against - we
# just search up to SM2_OPEN_GRIP_MAX steps in the open direction; a StallGuard
# trip within that = an object was detected/held. Keep this sized to the jaws'
# usable open travel so a "nothing there" run stops cleanly instead of grinding.
SM2_OPEN_GRIP_MAX = 800

# Boot release: how far PAST the known open travel to keep driving toward the
# open hard stop so the jaws fully seat there before the count is re-zeroed to
# OPEN. (open_to_stop watches StallGuard and normally stops ON the stop before
# using all of this.)
SM2_OPEN_STOP_MARGIN = 300

# The physical pause/start button is only wired in at Step 7 of the rebuild.
# Until then leave this False so its GPIO is never polled - guarantees no
# button-triggered motion during step-by-step bring-up.
PAUSE_BUTTON_ENABLED = False

# Hands-off rig: home and run the OUTSIDE pick the instant it powers on (no
# button/PC needed). On every boot the demo is reset to HOMING first, so it
# always re-homes to the limit switch before moving. Set False to go back to
# "first button press homes and starts" (see poll_button in main.py).
AUTO_START_ON_BOOT = True

STATE_FILE_PATH = "state.json"

# --------------------------------------------------------------------------
# Serial command verbs. Defined once so the GUI never hand-types a command
# string that the bridge does not actually implement.
# --------------------------------------------------------------------------

CMD_PING = "PING"
CMD_VERSION = "VERSION"
CMD_HELP = "HELP"
CMD_STATUS = "STATUS"
CMD_STATS = "STATS"
CMD_RESETSTATS = "RESETSTATS"
CMD_DEBUG = "DEBUG"

CMD_SM1 = "SM1"
CMD_SM2 = "SM2"
CMD_DEMO = "DEMO"
CMD_CAL = "CAL"

# SM1 / SM2 sub-verbs
SUB_ENABLE = "ENABLE"
SUB_DISABLE = "DISABLE"
SUB_SET = "SET"
SUB_JOG = "JOG"
SUB_GOTO = "GOTO"
SUB_MARK = "MARK"
SUB_STOP = "STOP"
SUB_OPEN = "OPEN"
SUB_CLOSE = "CLOSE"
SUB_FREEDRIVE = "FREEDRIVE"

# DEMO sub-verbs
SUB_START = "START"
SUB_PAUSE = "PAUSE"
SUB_RESUME = "RESUME"
SUB_RESET = "RESET"

# CAL sub-verbs
SUB_STATUS = "STATUS"
SUB_CLEAR = "CLEAR"


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
SM1_MAIN_STEPS = 6250

# --------------------------------------------------------------------------
# Gripper jaw states (SM2)
# --------------------------------------------------------------------------

GRIPPER_OPEN = "OPEN"
GRIPPER_CLOSED = "CLOSED"
GRIPPER_UNKNOWN = "UNKNOWN"

# --------------------------------------------------------------------------
# Demo cycle phases. The demo homes once (HOMING) and then runs an 8-phase
# loop; all gripper open/close happens at HOME and MAIN is only the far
# travel point. NEXT_PHASE is the full linear path - there is no branch (a
# CLOSE that reaches CLOSED with no object is normal here, not a fault).
#
# Cycle (matches the operator's spec):
#   HOMING
#   -> OPEN_AT_HOME_1      open gripper at HOME
#   -> OUT_TO_MAIN_1       move HOME -> MAIN (gripper open)
#   -> BACK_TO_HOME_1      move MAIN -> HOME
#   -> CLOSE_AT_HOME       close gripper at HOME
#   -> OUT_TO_MAIN_2       move HOME -> MAIN (gripper closed)
#   -> BACK_TO_HOME_2      move MAIN -> HOME
#   -> OPEN_AT_HOME_2      open gripper at HOME
#   -> CLOSE_AT_HOME_2     close gripper at HOME  (cycle_count += 1)
#   -> (back to OPEN_AT_HOME_1)
# --------------------------------------------------------------------------

PHASE_HOMING = "HOMING"
PHASE_OPEN_AT_HOME_1 = "OPEN_AT_HOME_1"
PHASE_OUT_TO_MAIN_1 = "OUT_TO_MAIN_1"
PHASE_BACK_TO_HOME_1 = "BACK_TO_HOME_1"
PHASE_CLOSE_AT_HOME = "CLOSE_AT_HOME"
PHASE_OUT_TO_MAIN_2 = "OUT_TO_MAIN_2"
PHASE_BACK_TO_HOME_2 = "BACK_TO_HOME_2"
PHASE_OPEN_AT_HOME_2 = "OPEN_AT_HOME_2"
PHASE_CLOSE_AT_HOME_2 = "CLOSE_AT_HOME_2"
PHASE_IDLE = "IDLE"

NEXT_PHASE = {
    PHASE_HOMING: PHASE_OPEN_AT_HOME_1,
    PHASE_OPEN_AT_HOME_1: PHASE_OUT_TO_MAIN_1,
    PHASE_OUT_TO_MAIN_1: PHASE_BACK_TO_HOME_1,
    PHASE_BACK_TO_HOME_1: PHASE_CLOSE_AT_HOME,
    PHASE_CLOSE_AT_HOME: PHASE_OUT_TO_MAIN_2,
    PHASE_OUT_TO_MAIN_2: PHASE_BACK_TO_HOME_2,
    PHASE_BACK_TO_HOME_2: PHASE_OPEN_AT_HOME_2,
    PHASE_OPEN_AT_HOME_2: PHASE_CLOSE_AT_HOME_2,
    PHASE_CLOSE_AT_HOME_2: PHASE_OPEN_AT_HOME_1,  # steady-state loop point
}

# --------------------------------------------------------------------------
# Tunable defaults. All are changeable at runtime over serial; these are
# just the values loaded fresh the first time (before any calibration file
# exists).
# --------------------------------------------------------------------------

DEFAULT_SPEED = "MEDIUM"
DEFAULT_TORQUE = "MEDIUM"
DEFAULT_STALLGUARD_THRESHOLD = 80     # 0-255, lower = more sensitive to load
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

BUTTON_DEBOUNCE_MS = 30        # a button reading must be stable this long to count

# Gripper CLOSE runs as one continuous move at this step half-period (us) so the
# motor holds a steady velocity - StallGuard4 needs that for a clean, high
# no-load reading. Faster (smaller) = stronger StallGuard signal, to a point.
SM2_GRIP_SPEED_US = 300

# Force-feedback grip (StallGuard). CLOSE drives PAST the fully-shut position by
# SM2_GRIP_OVERTRAVEL so the motor is FORCED to jam - on the object (early) or on
# the jaws' own hard stop (at full). StallGuard then always trips; we classify by
# WHERE it stopped: stalling at least SM2_GRIP_MARGIN steps short of fully-shut
# means an object was held. (Mark CLOSED at the true fully-shut position.)
GRIPPER_FORCE_FEEDBACK = True
SM2_GRIP_OVERTRAVEL = 300   # steps commanded past fully-shut to guarantee a jam
SM2_GRIP_MARGIN = 60        # stalling this far before fully-shut = a real grip

# Force-feedback OPEN (the 4-jaw demo, step 8): the jaws EXPAND (open direction)
# to grip a test tube from the inside, watching StallGuard, and stop the instant
# they meet the tube wall. Unlike CLOSE there's no fixed cap to jam against - we
# just search up to SM2_OPEN_GRIP_MAX steps in the open direction; a StallGuard
# trip within that = an object was detected/held. Keep this sized to the jaws'
# usable open travel so a "nothing there" run stops cleanly instead of grinding.
SM2_OPEN_GRIP_MAX = 800

# The physical pause/start button is only wired in at Step 7 of the rebuild.
# Until then leave this False so its GPIO is never polled - guarantees no
# button-triggered motion during step-by-step bring-up.
PAUSE_BUTTON_ENABLED = False

# On power-up the firmware never moves a motor by itself. When False the
# first push-button press homes and starts the cycle; set True only if you
# want a truly hands-off rig that homes and runs the instant it powers on.
AUTO_START_ON_BOOT = False

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

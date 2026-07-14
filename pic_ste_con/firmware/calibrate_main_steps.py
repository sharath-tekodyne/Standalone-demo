"""One-time calibration: measure the HOME -> MAIN step count for SM1.

Run this MANUALLY in Thonny (do NOT rename it to main.py - main.py auto-runs
the demo, this does not). It:

  1. Homes SM1 by driving CW into the limit switch (that point is HOME = 0).
  2. Lets you jog CW toward MAIN in increments you type, showing the running
     step total after each jog.
  3. When you type 'q' it prints the final HOME -> MAIN step count.

Then paste that number into protocol.SM1_MAIN_STEPS and re-upload protocol.py,
so the demo (main.py) travels exactly HOME <-> MAIN.

Usage at the prompt:
  <number>   jog that many steps CW toward MAIN (e.g. 200)
  -<number>  jog that many steps ACW back toward HOME (e.g. -50) for fine tuning
  q          finish and print the total

This reuses the exact same homing routine as the demo (PlatformAxis.home),
so the measured zero matches what the demo will home to.
"""

import protocol
from tmc2208 import TMC2208
from platform_axis import PlatformAxis

try:
    from machine import Pin  # type: ignore[import-not-found]
except ImportError:
    raise RuntimeError("calibrate_main_steps.py runs on the Pico (MicroPython) only")


def read_home_switch(pin):
    raw = pin.value()
    return (raw == 0) if protocol.HOME_SWITCH_ACTIVE_LOW else (raw == 1)


def main():
    motor = TMC2208(
        step_pin=protocol.SM1_STEP_PIN,
        dir_pin=protocol.SM1_DIR_PIN,
        en_pin=protocol.SM1_EN_PIN,
    )
    home_switch = Pin(protocol.SM1_HOME_SWITCH_PIN, Pin.IN, Pin.PULL_UP)

    # A throwaway in-memory state + no-op persist: this script never writes flash.
    state = {"sm1_position_steps": 0, "sm1_speed": protocol.DEFAULT_SPEED, "sm1_torque": protocol.DEFAULT_TORQUE, "sm1_speed_us_override": None}
    axis = PlatformAxis(motor, state, lambda: None, log=lambda m: print("DBG", m))

    print("Homing SM1 CW into the limit switch ...")
    motor.enable()
    axis.home(lambda: read_home_switch(home_switch))
    print("HOME found. position =", state["sm1_position_steps"])
    print("")
    print("Now jog toward MAIN. Type a step count (e.g. 200), a negative number")
    print("to back up (e.g. -50), or 'q' when the platform is exactly at MAIN.")

    while True:
        try:
            entry = input("steps> ").strip()
        except EOFError:
            break
        if entry.lower() in ("q", "quit", "done", ""):
            break
        try:
            delta = int(entry)
        except ValueError:
            print("  enter a whole number, or 'q' to finish")
            continue
        if delta == 0:
            continue
        direction = motor.CW if delta > 0 else motor.ACW
        axis.jog(direction, abs(delta))
        print("  position =", state["sm1_position_steps"])

    motor.disable()
    total = state["sm1_position_steps"]
    print("")
    print("=" * 52)
    print("HOME -> MAIN step count:", total)
    print("Set this in protocol.py:  SM1_MAIN_STEPS =", total)
    print("Then re-upload protocol.py to the Pico.")
    print("=" * 52)


if __name__ == "__main__":
    main()

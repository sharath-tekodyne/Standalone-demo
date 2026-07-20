"""Standalone SM1 limit-switch diagnostic - run MANUALLY in Thonny.

This is NOT main.py and imports nothing from the demo firmware except the pin
number, so it isolates the switch + wiring from all other code. Use it to
confirm the switch physically toggles its GPIO BEFORE any feature (homing,
the cycle) is built on top of it.

How to run:
  1. In Thonny, connect to the Pico and click Stop (to halt main.py).
  2. Open this file and click Run.
  3. Watch the Shell, and press/release the limit switch by hand.

Expected with a normally-open (NO) switch wired  C -> GPIO,  other leg -> GND:
  not pressed:  raw=1  -> RELEASED
  pressed:      raw=0  -> PRESSED

Reading the output:
  * You see 'CHANGE raw=1 -> RELEASED' / 'CHANGE raw=0 -> PRESSED' as you
    press/release  =>  switch + wiring are GOOD. Step 2 can proceed.
  * Pressing changes nothing (always raw=1)  =>  wiring/pin/ground problem,
    NOT software: check C->GP{pin}, the other leg to a Pico GND, and that the
    joints are solid.
  * It flips to raw=0 with nothing pressed, or many CHANGE lines while idle
    =>  noise/EMI or a missing common ground: tie switch GND to Pico GND,
    keep the switch wire away from the motor wires, add ~100nF GPIO->GND.
  * It reads inverted (pressed=1, idle=0)  =>  you are on the NC contact; set
    protocol.HOME_SWITCH_ACTIVE_LOW = False (we will do this in firmware).
"""

import time

try:
    from machine import Pin  # type: ignore[import-not-found]
except ImportError:
    raise SystemExit(
        "\nThis runs on the PICO (MicroPython), not on your PC.\n"
        "In Thonny: select the 'MicroPython (Raspberry Pi Pico)' interpreter,\n"
        "open this file, and click Run. (Your PC's Python has no 'machine' module.)\n"
    )

# Self-contained on purpose: this diagnostic imports nothing else, so it works
# no matter what firmware/protocol.py the Pico currently has. If you move the
# switch to a different GPIO, change SWITCH_PIN here.
SWITCH_PIN = 21       # GP21
ACTIVE_LOW = True     # NO switch to GND + internal pull-up => pressed reads 0

def is_pressed(raw):
    return (raw == 0) if ACTIVE_LOW else (raw == 1)


def main():
    switch = Pin(SWITCH_PIN, Pin.IN, Pin.PULL_UP)
    print("=" * 56)
    print("SM1 limit-switch test on GP{}  (active_low={})".format(SWITCH_PIN, ACTIVE_LOW))
    print("Press and release the switch. Ctrl-C / Stop to end.")
    print("=" * 56)

    last = None
    ticks = 0
    while True:
        raw = switch.value()
        state = "PRESSED" if is_pressed(raw) else "RELEASED"
        if raw != last:
            print("CHANGE  raw={}  -> {}".format(raw, state))
            last = raw
        ticks += 1
        if ticks % 50 == 0:  # ~1 s heartbeat so you know it is alive
            print("heartbeat  raw={}  {}".format(raw, state))
        time.sleep_ms(20)


# Only runs the loop when you explicitly Run this file - never on import, so
# it can't hijack the REPL during other checks.
if __name__ == "__main__":
    main()

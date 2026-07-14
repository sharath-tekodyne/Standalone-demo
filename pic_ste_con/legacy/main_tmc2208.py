"""MicroPython bridge for Pico 2W.

Save this on the Pico as main_tmc2208.py and run it from Thonny.
It listens on USB serial for text commands from the desktop GUI.

Commands:
- PING
- STATUS
- ENABLE
- DISABLE
- ESTOP
- SET DIR CW|ACW
- SET SPEED LOW|MEDIUM|HIGH
- SET TORQUE LOW|MEDIUM|HIGH
- SET CHUNK <steps>
- MOVE <steps>
- START
- STOP
- HELP
- VERSION
- DEBUG ON|OFF
- STATS
- RESETSTATS
"""

import sys
import time
try:
    import uselect  # type: ignore[import-not-found]
except ImportError:
    uselect = None

from tmc2208 import TMC2208


motor = TMC2208(step_pin=19, dir_pin=20, en_pin=18)
motor.disable()

BRIDGE_NAME = "main_tmc2208.py"
BRIDGE_VERSION = "1.1.0"
BOOT_TICKS = time.ticks_ms()

if uselect is None:
    raise RuntimeError("uselect is only available on MicroPython/Pico")

state = {
    "direction": "CW",
    "speed": "MEDIUM",
    "torque": "MEDIUM",
    "chunk": 120,
    "running": False,
    "enabled": False,
    "debug": True,
    "commands": 0,
    "errors": 0,
    "steps": 0,
    "last_command": "BOOT",
}

poll = uselect.poll()
poll.register(sys.stdin, uselect.POLLIN)


def debug(message):
    if state["debug"]:
        print("DBG {}".format(message))


def reply_ok(message):
    print("OK {}".format(message))


def reply_err(message):
    print("ERR {}".format(message))


def direction_value():
    return TMC2208.CW if state["direction"] == "CW" else TMC2208.ACW


def parse_int(value, label, minimum=1):
    try:
        parsed = int(str(value).strip())
    except Exception:
        raise ValueError("{} must be a whole number".format(label))
    if parsed < minimum:
        raise ValueError("{} must be at least {}".format(label, minimum))
    return parsed


def uptime_ms():
    return time.ticks_diff(time.ticks_ms(), BOOT_TICKS)


def set_enabled(enabled):
    if enabled:
        motor.enable()
    else:
        motor.disable()
    state["enabled"] = bool(enabled)


def stop_motion(disable=True):
    state["running"] = False
    if disable:
        set_enabled(False)


def set_param(name, value):
    name = name.upper().strip()
    value = value.upper().strip()

    if name == "DIR":
        if value not in ("CW", "ACW"):
            raise ValueError("DIR must be CW or ACW")
        state["direction"] = value
        return

    if name in ("SPEED", "TORQUE"):
        if value not in ("LOW", "MEDIUM", "HIGH"):
            raise ValueError("{} must be LOW/MEDIUM/HIGH".format(name))
        state[name.lower()] = value
        return

    if name == "CHUNK":
        state["chunk"] = parse_int(value, "CHUNK")
        return

    raise ValueError("unknown parameter")


def status_line():
    return "STATUS dir={} speed={} torque={} chunk={} running={} enabled={} steps={} commands={} errors={} uptime_ms={}".format(
        state["direction"],
        state["speed"],
        state["torque"],
        state["chunk"],
        int(state["running"]),
        int(state["enabled"]),
        state["steps"],
        state["commands"],
        state["errors"],
        uptime_ms(),
    )


def help_line():
    return "HELP PING STATUS ENABLE DISABLE ESTOP SET DIR|SPEED|TORQUE|CHUNK MOVE START STOP DEBUG ON|OFF STATS RESETSTATS VERSION"


def handle_command(line):
    line = line.strip()
    if not line:
        return

    tokens = line.split()
    cmd = tokens[0].upper()
    state["commands"] += 1
    state["last_command"] = line
    debug("CMD {}".format(line))

    if cmd == "PING":
        reply_ok("PONG {} {}".format(BRIDGE_NAME, BRIDGE_VERSION))
        return

    if cmd == "VERSION":
        reply_ok("VERSION bridge={} version={} micropython={}".format(BRIDGE_NAME, BRIDGE_VERSION, sys.implementation.name))
        return

    if cmd == "HELP":
        reply_ok(help_line())
        return

    if cmd == "STATUS":
        reply_ok(status_line())
        return

    if cmd == "ENABLE":
        set_enabled(True)
        reply_ok("ENABLE")
        return

    if cmd == "DISABLE":
        stop_motion()
        reply_ok("DISABLE")
        return

    if cmd == "ESTOP":
        stop_motion()
        reply_ok("ESTOP")
        return

    if cmd == "SET":
        if len(tokens) != 3:
            raise ValueError("usage: SET DIR|SPEED|TORQUE|CHUNK VALUE")
        set_param(tokens[1], tokens[2])
        reply_ok("SET {} {}".format(tokens[1].upper(), tokens[2].upper()))
        return

    if cmd == "DEBUG":
        if len(tokens) != 2 or tokens[1].upper() not in ("ON", "OFF"):
            raise ValueError("usage: DEBUG ON|OFF")
        state["debug"] = tokens[1].upper() == "ON"
        reply_ok("DEBUG {}".format("ON" if state["debug"] else "OFF"))
        return

    if cmd == "STATS":
        reply_ok("STATS bridge={} version={} last={} {}".format(
            BRIDGE_NAME, BRIDGE_VERSION, state["last_command"], status_line()
        ))
        return

    if cmd == "RESETSTATS":
        state["commands"] = 0
        state["errors"] = 0
        state["steps"] = 0
        reply_ok("RESETSTATS")
        return

    if cmd == "MOVE":
        if len(tokens) != 2:
            raise ValueError("usage: MOVE <steps>")
        steps = parse_int(tokens[1], "steps")
        stop_motion(disable=False)
        completed = motor.move_with_presets(
            direction=direction_value(),
            steps=steps,
            speed=state["speed"],
            torque=state["torque"],
        )
        state["steps"] += completed
        reply_ok("MOVE requested={} completed={} total_steps={}".format(steps, completed, state["steps"]))
        return

    if cmd == "START":
        state["running"] = True
        set_enabled(True)
        reply_ok("START")
        return

    if cmd == "STOP":
        stop_motion()
        reply_ok("STOP")
        return

    raise ValueError("unknown command")


debug("BOOT {} v{}".format(BRIDGE_NAME, BRIDGE_VERSION))
debug("PINMAP STEP=GP19 DIR=GP20 EN=GP18")
print("READY {} v{}".format(BRIDGE_NAME, BRIDGE_VERSION))
reply_ok(status_line())

while True:
    if state["running"]:
        try:
            completed = motor.run_chunk(
                direction=direction_value(),
                chunk_steps=state["chunk"],
                speed=state["speed"],
                torque=state["torque"],
            )
            state["steps"] += completed
        except Exception as exc:
            stop_motion()
            state["errors"] += 1
            reply_err("RUN {}: {}".format(type(exc).__name__, exc))

    if poll.poll(0):
        incoming = sys.stdin.readline()
        if incoming:
            try:
                handle_command(incoming)
            except Exception as exc:
                state["errors"] += 1
                reply_err("{}: {}".format(type(exc).__name__, exc))

    if not state["running"]:
        time.sleep_ms(10)

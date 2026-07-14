"""MicroPython bridge for the Pico 2W gripper demo.

Save this file as main.py (and the rest of firmware/*.py, plus protocol.py
from the repo root) onto the Pico - see SETUP.md. Because it is named
main.py, MicroPython auto-runs it on every power-up/reset, with no need to
launch it from Thonny first.

It listens on USB serial for text commands from the desktop GUI and drives:

- SM1, the TMC2208 platform axis (HOME via limit switch / MAIN by step count)
- SM2, the TMC2209 gripper axis (OPEN / CLOSED, with StallGuard grip check)
- the persisted demo cycle state machine (demo_cycle.py)
- a physical push-button (latching pause/resume, and start on the first press)

Run `HELP` for the full command list once connected.

Safety note: demo_running is always forced to False immediately after
loading saved state (see below), even if the demo was mid-cycle when power
was lost. Autostart must never resume physical motion on its own - after a
power cycle an operator has to press the physical button (or send DEMO
RESUME / DEMO START), the same as after any other pause. Set
protocol.AUTO_START_ON_BOOT = True only if you want a hands-off rig that
homes and runs the instant it powers on.
"""

import sys
import time

try:
    import uselect
except ImportError:
    uselect = None

try:
    from machine import Pin
except ImportError:
    Pin = None

import protocol
from tmc2208 import TMC2208
from tmc2209 import TMC2209
from state_store import StateStore
from platform_axis import PlatformAxis
from gripper_axis import GripperAxis
from demo_cycle import DemoCycle

if uselect is None:
    raise RuntimeError("uselect is only available on MicroPython/Pico")

BRIDGE_NAME = "main.py"
BRIDGE_VERSION = "2.0.0"
BOOT_TICKS = time.ticks_ms()

DEFAULT_STATE = {
    "sm1_position_steps": 0,
    "sm1_main_steps": None,   # HOME->MAIN distance calibrated at runtime (SM1 MARK MAIN); None -> use protocol.SM1_MAIN_STEPS
    "sm1_speed": protocol.DEFAULT_SPEED,
    "sm1_torque": protocol.DEFAULT_TORQUE,
    "sm1_speed_us_override": None,
    "sm1_enabled": False,
    "sm2_position_steps": 0,
    "sm2_closed_steps": None,
    "sm2_speed": protocol.DEFAULT_SPEED,
    "sm2_torque": protocol.DEFAULT_TORQUE,
    "sm2_speed_us_override": None,
    "sm2_stallguard_threshold": protocol.DEFAULT_STALLGUARD_THRESHOLD,
    "sm2_enabled": False,
    "gripper_state": protocol.GRIPPER_UNKNOWN,
    "demo_phase": None,
    "demo_running": False,
    "needs_attention": False,
    "cycle_count": 0,
}

runtime = {
    "debug": True,
    "commands": 0,
    "errors": 0,
    "last_command": "BOOT",
}

store = StateStore()
state = store.load(DEFAULT_STATE)

# Auto-run on boot must never resume physical motion by itself - always
# come up paused, no matter what was persisted, so an operator has to
# explicitly click Resume/DEMO RESUME after any power cycle.
needs_boot_save = False
if state.get("demo_running"):
    state["demo_running"] = False
    needs_boot_save = True
# Both drivers are physically disabled below regardless of saved state -
# keep the reported latch truthful rather than claiming "enabled" for a
# motor that just booted de-energized.
if state.get("sm1_enabled") or state.get("sm2_enabled"):
    state["sm1_enabled"] = False
    state["sm2_enabled"] = False
    needs_boot_save = True
if needs_boot_save:
    store.save()


def persist():
    store.save(state)


motor1 = TMC2208(step_pin=protocol.SM1_STEP_PIN, dir_pin=protocol.SM1_DIR_PIN, en_pin=protocol.SM1_EN_PIN)
motor1.disable()

motor2 = TMC2209(
    step_pin=protocol.SM2_STEP_PIN,
    dir_pin=protocol.SM2_DIR_PIN,
    en_pin=protocol.SM2_EN_PIN,
    diag_pin=protocol.SM2_DIAG_PIN,
    uart_id=protocol.SM2_UART_ID,
    tx_pin=protocol.SM2_UART_TX_PIN,
    rx_pin=protocol.SM2_UART_RX_PIN,
)
motor2.disable()

sm2_ready = True
try:
    motor2.set_torque_preset(state["sm2_torque"])
    motor2.configure_stallguard(state["sm2_stallguard_threshold"])
except Exception as exc:
    sm2_ready = False
    print("DBG SM2 UART setup failed - is the TMC2209 wired/powered? {}: {}".format(type(exc).__name__, exc))

# SM1 home limit switch and the physical pause button. Both wired to GND with
# the internal pull-up, so a raw read of 0 means "actuated" when *_ACTIVE_LOW.
home_switch_pin = Pin(protocol.SM1_HOME_SWITCH_PIN, Pin.IN, Pin.PULL_UP)
pause_button_pin = Pin(protocol.PAUSE_BUTTON_PIN, Pin.IN, Pin.PULL_UP)


def read_home_switch():
    raw = home_switch_pin.value()
    return (raw == 0) if protocol.HOME_SWITCH_ACTIVE_LOW else (raw == 1)


def read_pause_button():
    raw = pause_button_pin.value()
    return (raw == 0) if protocol.PAUSE_BUTTON_ACTIVE_LOW else (raw == 1)


poll = uselect.poll()
poll.register(sys.stdin, uselect.POLLIN)


def debug(message):
    if runtime["debug"]:
        print("DBG {}".format(message))


def reply_ok(message):
    print("OK {}".format(message))


def reply_err(message):
    print("ERR {}".format(message))


def uptime_ms():
    return time.ticks_diff(time.ticks_ms(), BOOT_TICKS)


platform = PlatformAxis(motor1, state, persist, log=debug)
gripper = GripperAxis(motor2, state, persist, log=debug)
demo = DemoCycle(platform, gripper, state, persist, read_home_switch)


def set_sm1_enabled(enabled):
    if enabled:
        motor1.enable()
    else:
        motor1.disable()
    state["sm1_enabled"] = bool(enabled)
    persist()


def set_sm2_enabled(enabled):
    if enabled:
        motor2.enable()
    else:
        motor2.disable()
    state["sm2_enabled"] = bool(enabled)
    persist()


def require_sm1_enabled():
    if not state.get("sm1_enabled", False):
        raise RuntimeError("SM1 is disabled - click Enable (or send SM1 ENABLE) first")


def require_sm2_enabled():
    if not state.get("sm2_enabled", False):
        raise RuntimeError("SM2 is disabled - click Enable (or send SM2 ENABLE) first")


def pause_demo_if_running(reason):
    if state.get("demo_running", False):
        demo.pause()
        debug("demo auto-paused: {}".format(reason))


def parse_int(value, label, minimum=None, maximum=None):
    try:
        parsed = int(str(value).strip())
    except Exception:
        raise ValueError("{} must be a whole number".format(label))
    if minimum is not None and parsed < minimum:
        raise ValueError("{} must be at least {}".format(label, minimum))
    if maximum is not None and parsed > maximum:
        raise ValueError("{} must be at most {}".format(label, maximum))
    return parsed


def parse_direction(value):
    value = value.upper().strip()
    if value == "CW":
        return 1
    if value == "ACW":
        return 0
    raise ValueError("direction must be CW or ACW")


def status_line():
    sm1_speed_us = state.get("sm1_speed_us_override")
    sm2_speed_us = state.get("sm2_speed_us_override")
    return (
        "STATUS "
        "sm1_pos={sm1_position_steps} sm1_main={sm1_main_steps} "
        "sm1_speed={sm1_speed} sm1_torque={sm1_torque} sm1_speed_us={sm1_speed_us} "
        "sm1_enabled={sm1_enabled_int} home_switch={home_switch_int} "
        "sm2_pos={sm2_position_steps} sm2_closed={sm2_closed_steps} "
        "sm2_speed={sm2_speed} sm2_torque={sm2_torque} sm2_speed_us={sm2_speed_us} "
        "sm2_sgthrs={sm2_stallguard_threshold} sm2_enabled={sm2_enabled_int} "
        "gripper={gripper_state} "
        "demo_phase={demo_phase} demo_running={demo_running_int} needs_attention={needs_attention_int} "
        "cycle_count={cycle_count} pause_btn={pause_btn_int} "
        "sm2_ready={sm2_ready_int} commands={commands} errors={errors} uptime_ms={uptime_ms}"
    ).format(
        sm1_position_steps=state["sm1_position_steps"],
        sm1_main_steps=(state.get("sm1_main_steps") or protocol.SM1_MAIN_STEPS or "None"),
        sm1_speed=state["sm1_speed"],
        sm1_torque=state["sm1_torque"],
        sm1_speed_us=sm1_speed_us if sm1_speed_us is not None else "AUTO",
        sm1_enabled_int=int(state.get("sm1_enabled", False)),
        home_switch_int=int(read_home_switch()),
        sm2_position_steps=state["sm2_position_steps"],
        sm2_closed_steps=state["sm2_closed_steps"],
        sm2_speed=state["sm2_speed"],
        sm2_torque=state["sm2_torque"],
        sm2_speed_us=sm2_speed_us if sm2_speed_us is not None else "AUTO",
        sm2_stallguard_threshold=state["sm2_stallguard_threshold"],
        sm2_enabled_int=int(state.get("sm2_enabled", False)),
        gripper_state=state["gripper_state"],
        demo_phase=state["demo_phase"],
        demo_running_int=int(state["demo_running"]),
        needs_attention_int=int(state["needs_attention"]),
        cycle_count=state["cycle_count"],
        pause_btn_int=int(read_pause_button()),
        sm2_ready_int=int(sm2_ready),
        commands=runtime["commands"],
        errors=runtime["errors"],
        uptime_ms=uptime_ms(),
    )


def help_line():
    return (
        "HELP PING VERSION STATUS STATS RESETSTATS DEBUG ON|OFF ESTOP | "
        "SM1 ENABLE|DISABLE|STOP|FREEDRIVE SM1 SET SPEED|TORQUE LOW|MEDIUM|HIGH SM1 SET SPEEDUS <us>|AUTO "
        "SM1 SET MAINSTEPS <n>|CLEAR SM1 HOME SM1 JOG CW|ACW <steps> SM1 GOTO HOME|MAIN SM1 GOTO STEPS <n> SM1 MARK HOME|MAIN | "
        "SM2 ENABLE|DISABLE|STOP|FREEDRIVE SM2 SET SPEED|TORQUE LOW|MEDIUM|HIGH SM2 SET SPEEDUS <us>|AUTO "
        "SM2 SET STALLTHRESHOLD <0-255> SM2 JOG CW|ACW <steps> SM2 OPEN SM2 CLOSE SM2 GOTO STEPS <n> "
        "SM2 MARK OPEN|CLOSED | "
        "DEMO START|PAUSE|RESUME|RESET | CAL STATUS|CLEAR"
    )


def require_demo_idle():
    if state.get("demo_running", False):
        raise RuntimeError("Stop or pause the demo before sending manual axis commands")


def handle_sm1(tokens):
    if len(tokens) < 1:
        raise ValueError("usage: SM1 <ENABLE|DISABLE|STOP|FREEDRIVE|SET|HOME|JOG|GOTO|MARK> ...")
    sub = tokens[0].upper()

    if sub == "ENABLE":
        set_sm1_enabled(True)
        reply_ok("SM1 ENABLE")
        return
    if sub == "DISABLE" or sub == "STOP":
        set_sm1_enabled(False)
        pause_demo_if_running("SM1 {}".format(sub))
        reply_ok("SM1 {}".format(sub))
        return
    if sub == "FREEDRIVE":
        set_sm1_enabled(False)
        pause_demo_if_running("SM1 FREEDRIVE")
        reply_ok("SM1 FREEDRIVE - motor de-energized, move it by hand, then re-run calibration (SM1 MARK ...) before resuming")
        return
    if sub == "SET":
        if len(tokens) == 3 and tokens[1].upper() == "SPEEDUS":
            value = tokens[2].upper()
            if value == "AUTO":
                state["sm1_speed_us_override"] = None
            else:
                state["sm1_speed_us_override"] = parse_int(value, "SPEEDUS", minimum=100)
            persist()
            reply_ok("SM1 SET SPEEDUS {}".format(value))
            return
        if len(tokens) == 3 and tokens[1].upper() == "MAINSTEPS":
            require_demo_idle()
            value = tokens[2].upper()
            if value == "CLEAR":
                state["sm1_main_steps"] = None
            else:
                n = parse_int(value, "MAINSTEPS")
                if n == 0:
                    raise ValueError("MAINSTEPS cannot be 0 (that is HOME)")
                state["sm1_main_steps"] = n
            persist()
            reply_ok("SM1 SET MAINSTEPS {}".format(value))
            return
        if len(tokens) != 3:
            raise ValueError("usage: SM1 SET SPEED|TORQUE LOW|MEDIUM|HIGH | SM1 SET SPEEDUS <us>|AUTO | SM1 SET MAINSTEPS <n>|CLEAR")
        name, value = tokens[1].upper(), tokens[2].upper()
        if name == "SPEED":
            if value not in protocol.SPEED_LEVELS:
                raise ValueError("SPEED must be LOW/MEDIUM/HIGH")
            state["sm1_speed"] = value
            state["sm1_speed_us_override"] = None  # an explicit preset takes priority over any manual override
        elif name == "TORQUE":
            if value not in protocol.TORQUE_LEVELS:
                raise ValueError("TORQUE must be LOW/MEDIUM/HIGH")
            state["sm1_torque"] = value
        else:
            raise ValueError("SM1 SET only supports SPEED, TORQUE, or SPEEDUS")
        persist()
        reply_ok("SM1 SET {} {}".format(name, value))
        return
    if sub == "HOME":
        require_demo_idle()
        require_sm1_enabled()
        platform.home(read_home_switch, should_pause=None)
        reply_ok("SM1 HOME position={}".format(state["sm1_position_steps"]))
        return
    if sub == "JOG":
        require_demo_idle()
        require_sm1_enabled()
        if len(tokens) != 3:
            raise ValueError("usage: SM1 JOG CW|ACW <steps>")
        direction = parse_direction(tokens[1])
        steps = parse_int(tokens[2], "steps", minimum=1)
        completed = platform.jog(direction, steps)
        reply_ok("SM1 JOG completed={} position={}".format(completed, state["sm1_position_steps"]))
        return
    if sub == "GOTO":
        require_demo_idle()
        require_sm1_enabled()
        if len(tokens) < 2:
            raise ValueError("usage: SM1 GOTO HOME|MAIN | SM1 GOTO STEPS <n>")
        if tokens[1].upper() == "STEPS":
            if len(tokens) != 3:
                raise ValueError("usage: SM1 GOTO STEPS <n>")
            target = parse_int(tokens[2], "STEPS")
            platform.move_to_absolute(target, should_pause=None)
            reply_ok("SM1 GOTO STEPS {} position={}".format(target, state["sm1_position_steps"]))
            return
        name = tokens[1].upper()
        platform.move_to(name, should_pause=None)
        reply_ok("SM1 GOTO {} position={}".format(name, state["sm1_position_steps"]))
        return
    if sub == "MARK":
        require_demo_idle()
        if len(tokens) != 2:
            raise ValueError("usage: SM1 MARK HOME|MAIN")
        name = tokens[1].upper()
        platform.mark(name)
        reply_ok("SM1 MARK {} position={}".format(name, state["sm1_position_steps"]))
        return

    raise ValueError("unknown SM1 sub-command: {}".format(sub))


def handle_sm2(tokens):
    if len(tokens) < 1:
        raise ValueError("usage: SM2 <ENABLE|DISABLE|STOP|FREEDRIVE|SET|JOG|OPEN|CLOSE|GOTO|MARK> ...")
    sub = tokens[0].upper()

    if sub == "ENABLE":
        set_sm2_enabled(True)
        reply_ok("SM2 ENABLE")
        return
    if sub == "DISABLE" or sub == "STOP":
        set_sm2_enabled(False)
        pause_demo_if_running("SM2 {}".format(sub))
        reply_ok("SM2 {}".format(sub))
        return
    if sub == "FREEDRIVE":
        set_sm2_enabled(False)
        pause_demo_if_running("SM2 FREEDRIVE")
        reply_ok("SM2 FREEDRIVE - motor de-energized, move it by hand, then re-run calibration (SM2 MARK ...) before resuming")
        return
    if sub == "SET":
        if len(tokens) == 3 and tokens[1].upper() == "STALLTHRESHOLD":
            threshold = parse_int(tokens[2], "STALLTHRESHOLD", minimum=0, maximum=255)
            motor2.configure_stallguard(threshold)
            state["sm2_stallguard_threshold"] = threshold
            persist()
            reply_ok("SM2 SET STALLTHRESHOLD {}".format(threshold))
            return
        if len(tokens) == 3 and tokens[1].upper() == "SPEEDUS":
            value = tokens[2].upper()
            if value == "AUTO":
                state["sm2_speed_us_override"] = None
            else:
                state["sm2_speed_us_override"] = parse_int(value, "SPEEDUS", minimum=100)
            persist()
            reply_ok("SM2 SET SPEEDUS {}".format(value))
            return
        if len(tokens) != 3:
            raise ValueError("usage: SM2 SET SPEED|TORQUE LOW|MEDIUM|HIGH | SM2 SET SPEEDUS <us>|AUTO | SM2 SET STALLTHRESHOLD <0-255>")
        name, value = tokens[1].upper(), tokens[2].upper()
        if name == "SPEED":
            if value not in protocol.SPEED_LEVELS:
                raise ValueError("SPEED must be LOW/MEDIUM/HIGH")
            state["sm2_speed"] = value
            state["sm2_speed_us_override"] = None  # an explicit preset takes priority over any manual override
        elif name == "TORQUE":
            if value not in protocol.TORQUE_LEVELS:
                raise ValueError("TORQUE must be LOW/MEDIUM/HIGH")
            motor2.set_torque_preset(value)
            state["sm2_torque"] = value
        else:
            raise ValueError("SM2 SET only supports SPEED, TORQUE, SPEEDUS, or STALLTHRESHOLD")
        persist()
        reply_ok("SM2 SET {} {}".format(name, value))
        return
    if sub == "JOG":
        require_demo_idle()
        require_sm2_enabled()
        if len(tokens) != 3:
            raise ValueError("usage: SM2 JOG CW|ACW <steps>")
        direction = parse_direction(tokens[1])
        steps = parse_int(tokens[2], "steps", minimum=1)
        stalled, completed = gripper.jog(direction, steps)
        reply_ok("SM2 JOG completed={} stalled={} position={}".format(completed, int(stalled), state["sm2_position_steps"]))
        return
    if sub == "OPEN":
        require_demo_idle()
        require_sm2_enabled()
        gripper.open_gripper(should_pause=None)
        reply_ok("SM2 OPEN position={}".format(state["sm2_position_steps"]))
        return
    if sub == "CLOSE":
        require_demo_idle()
        require_sm2_enabled()
        gripped = gripper.close_and_verify_grip(should_pause=None)
        reply_ok("SM2 CLOSE gripped={} position={}".format(int(bool(gripped)), state["sm2_position_steps"]))
        return
    if sub == "GOTO":
        require_demo_idle()
        require_sm2_enabled()
        if len(tokens) != 3 or tokens[1].upper() != "STEPS":
            raise ValueError("usage: SM2 GOTO STEPS <n>")
        target = parse_int(tokens[2], "STEPS")
        result = gripper.goto_steps(target, should_pause=None)
        reply_ok("SM2 GOTO STEPS {} result={} position={}".format(target, result, state["sm2_position_steps"]))
        return
    if sub == "MARK":
        require_demo_idle()
        if len(tokens) != 2:
            raise ValueError("usage: SM2 MARK OPEN|CLOSED")
        name = tokens[1].upper()
        gripper.mark(name)
        reply_ok("SM2 MARK {} position={}".format(name, state["sm2_position_steps"]))
        return

    raise ValueError("unknown SM2 sub-command: {}".format(sub))


def handle_demo(tokens):
    if len(tokens) < 1:
        raise ValueError("usage: DEMO START|PAUSE|RESUME|RESET")
    sub = tokens[0].upper()

    if sub == "START":
        demo.start()
        set_sm1_enabled(True)
        set_sm2_enabled(True)
        reply_ok("DEMO START phase={}".format(state["demo_phase"]))
        return
    if sub == "PAUSE":
        demo.pause()
        reply_ok("DEMO PAUSE phase={}".format(state["demo_phase"]))
        return
    if sub == "RESUME":
        demo.resume()
        set_sm1_enabled(True)
        set_sm2_enabled(True)
        reply_ok("DEMO RESUME phase={}".format(state["demo_phase"]))
        return
    if sub == "RESET":
        demo.reset()
        reply_ok("DEMO RESET")
        return

    raise ValueError("unknown DEMO sub-command: {}".format(sub))


def handle_cal(tokens):
    if len(tokens) != 1:
        raise ValueError("usage: CAL STATUS|CLEAR")
    sub = tokens[0].upper()

    if sub == "STATUS":
        reply_ok(
            "CAL STATUS sm1_main={} sm2_closed={} ready={}".format(
                int(platform.is_calibrated()),
                int(state["sm2_closed_steps"] is not None),
                int(demo.is_calibrated()),
            )
        )
        return
    if sub == "CLEAR":
        require_demo_idle()
        # Clears the runtime-calibrated MAIN offset and the SM2 CLOSED mark.
        # HOME needs no calibration (limit switch); if protocol.SM1_MAIN_STEPS
        # is set as a constant, MAIN falls back to it after clearing.
        state["sm1_main_steps"] = None
        state["sm2_closed_steps"] = None
        persist()
        reply_ok("CAL CLEAR")
        return

    raise ValueError("unknown CAL sub-command: {}".format(sub))


def handle_command(line):
    line = line.strip()
    if not line:
        return

    tokens = line.split()
    cmd = tokens[0].upper()
    runtime["commands"] += 1
    runtime["last_command"] = line
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
    if cmd == "STATS":
        reply_ok("STATS last={} {}".format(runtime["last_command"], status_line()))
        return
    if cmd == "RESETSTATS":
        runtime["commands"] = 0
        runtime["errors"] = 0
        reply_ok("RESETSTATS")
        return
    if cmd == "DEBUG":
        if len(tokens) != 2 or tokens[1].upper() not in ("ON", "OFF"):
            raise ValueError("usage: DEBUG ON|OFF")
        runtime["debug"] = tokens[1].upper() == "ON"
        reply_ok("DEBUG {}".format("ON" if runtime["debug"] else "OFF"))
        return
    if cmd == "ESTOP":
        demo.pause()
        set_sm1_enabled(False)
        set_sm2_enabled(False)
        reply_ok("ESTOP")
        return
    if cmd == "SM1":
        handle_sm1(tokens[1:])
        return
    if cmd == "SM2":
        handle_sm2(tokens[1:])
        return
    if cmd == "DEMO":
        handle_demo(tokens[1:])
        return
    if cmd == "CAL":
        handle_cal(tokens[1:])
        return

    raise ValueError("unknown command: {}".format(cmd))


def poll_incoming():
    if poll.poll(0):
        incoming = sys.stdin.readline()
        if incoming:
            try:
                handle_command(incoming)
            except Exception as exc:
                runtime["errors"] += 1
                reply_err("{}: {}".format(type(exc).__name__, exc))


# Debounced state for the physical pause button. It is a latching toggle:
# a press pauses a running demo, a press resumes a paused one, and the very
# first press (no phase yet) homes and starts the cycle. Only the press edge
# acts; releasing does nothing.
button_state = {
    "pressed": False,        # debounced logical state
    "last_raw": False,       # last raw sample
    "last_change_ms": time.ticks_ms(),
}


def _on_button_press():
    if state.get("demo_running", False):
        demo.pause()
        debug("button: paused phase={}".format(state.get("demo_phase")))
        return
    if state.get("demo_phase") is not None:
        demo.resume()
        set_sm1_enabled(True)
        set_sm2_enabled(True)
        debug("button: resumed phase={}".format(state.get("demo_phase")))
        return
    demo.start()
    set_sm1_enabled(True)
    set_sm2_enabled(True)
    debug("button: started phase={}".format(state.get("demo_phase")))


def poll_button():
    raw = read_pause_button()
    now = time.ticks_ms()
    if raw != button_state["last_raw"]:
        # bouncing - restart the stability timer, don't act yet
        button_state["last_raw"] = raw
        button_state["last_change_ms"] = now
        return
    if time.ticks_diff(now, button_state["last_change_ms"]) < protocol.BUTTON_DEBOUNCE_MS:
        return
    if raw == button_state["pressed"]:
        return  # stable, but no logical change since last time
    button_state["pressed"] = raw
    if raw:  # act only on the press edge, not the release
        try:
            _on_button_press()
        except Exception as exc:
            runtime["errors"] += 1
            reply_err("BUTTON {}: {}".format(type(exc).__name__, exc))


def poll_inputs():
    """Service both input sources - serial commands and the pause button."""
    poll_incoming()
    poll_button()


debug("BOOT {} v{}".format(BRIDGE_NAME, BRIDGE_VERSION))
debug(
    "PINMAP SM1 STEP={} DIR={} EN={} HOME_SW={} | SM2 STEP={} DIR={} EN={} DIAG={} UART{} TX={} RX={} | BUTTON={}".format(
        protocol.SM1_STEP_PIN, protocol.SM1_DIR_PIN, protocol.SM1_EN_PIN, protocol.SM1_HOME_SWITCH_PIN,
        protocol.SM2_STEP_PIN, protocol.SM2_DIR_PIN, protocol.SM2_EN_PIN, protocol.SM2_DIAG_PIN,
        protocol.SM2_UART_ID, protocol.SM2_UART_TX_PIN, protocol.SM2_UART_RX_PIN,
        protocol.PAUSE_BUTTON_PIN,
    )
)
print("READY {} v{}".format(BRIDGE_NAME, BRIDGE_VERSION))
reply_ok(status_line())

# Opt-in hands-off mode: home and run the instant we power on. Off by default
# so nothing moves until a human presses the button (or the GUI starts it).
if protocol.AUTO_START_ON_BOOT and demo.is_calibrated():
    try:
        demo.start()
        set_sm1_enabled(True)
        set_sm2_enabled(True)
        debug("AUTO_START_ON_BOOT: started phase={}".format(state.get("demo_phase")))
    except Exception as exc:
        runtime["errors"] += 1
        reply_err("AUTOSTART {}: {}".format(type(exc).__name__, exc))

while True:
    try:
        demo.tick(poll_inputs)
    except Exception as exc:
        demo.pause()
        state["needs_attention"] = True
        persist()
        runtime["errors"] += 1
        reply_err("DEMO {}: {}".format(type(exc).__name__, exc))

    poll_inputs()

    if not state.get("demo_running", False):
        time.sleep_ms(10)

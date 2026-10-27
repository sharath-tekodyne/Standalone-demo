"""Self-check for the demo phase state machines (run on desktop CPython):

    python firmware/test_demo_cycle.py

Not flashed to the Pico (push.ps1 doesn't upload it). Uses fake axes so it
needs no hardware - it proves both demo modes: the phase order, the once-only
priming (RELEASE then HOME), the moves each phase drives to, and cycle_count.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))                       # demo_cycle.py
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))      # protocol.py (repo root)

import protocol
from demo_cycle import DemoCycle


class FakePlatform:
    def __init__(self, calls):
        self.calls = calls

    def home(self, switch_read, should_pause=None):
        self.calls.append(("home", None))
        return True

    def move_to_absolute(self, target, should_pause=None):
        self.calls.append(("move", target))
        return True


class FakeGripper:
    def __init__(self, calls):
        self.calls = calls

    def is_calibrated(self):
        return True

    def set_torque(self, level):
        self.torque = level

    def set_stallguard_threshold(self, threshold):
        self.threshold = threshold

    def open_gripper(self, should_pause=None):
        self.calls.append(("open", None))
        return True

    def open_to_stop(self, should_pause=None):
        self.calls.append(("open_to_stop", None))
        return True

    def close_and_verify_grip(self, should_pause=None):
        self.calls.append(("close", None))
        return False  # nothing gripped - a normal outcome, still advances


def drive(next_phase, cycle_end):
    """Run one demo mode to 2 completed cycles; return (calls, state, seen)."""
    protocol.NEXT_PHASE = next_phase
    protocol.CYCLE_END_PHASE = cycle_end
    calls = []
    state = {"demo_phase": None, "demo_running": False, "cycle_count": 0,
             "needs_attention": False}
    gripper = FakeGripper(calls)
    demo = DemoCycle(FakePlatform(calls), gripper, state,
                     persist=lambda: None, switch_read=lambda: True)

    demo.start()
    assert state["demo_phase"] == protocol.PHASE_RELEASE, state["demo_phase"]
    assert state["sm1_speed_us_override"] == protocol.SM1_DEMO_SPEED_US
    # The demo must NOT force gripper speed/current/threshold - those are
    # inherited from state (GUI-tuned), so it must not clear the speed override.
    assert "sm2_speed_us_override" not in state, "demo must not touch SM2 grip speed"

    seen = []
    noop = lambda: None
    for _ in range(60):
        phase = state["demo_phase"]
        demo.tick(noop)
        if state["demo_phase"] != phase:
            seen.append(phase)
        if state["cycle_count"] >= 2:
            break
    return calls, state, seen


def check(name, calls, state, seen, body):
    # priming (release + home) happens exactly once, then the body repeats.
    expected = [protocol.PHASE_RELEASE, protocol.PHASE_HOMING] + body + body
    assert seen == expected, (name, seen)
    assert state["cycle_count"] == 2, (name, state["cycle_count"])
    assert seen.count(protocol.PHASE_HOMING) == 1, name + ": homing once"
    assert seen.count(protocol.PHASE_RELEASE) == 1, name + ": release once"
    assert seen.index(protocol.PHASE_RELEASE) < seen.index(protocol.PHASE_HOMING), \
        name + ": release before homing"
    # boot release must force the jaws to the OPEN stop, not a relative open
    assert calls[0] == ("open_to_stop", None), (name, calls[0])


def run():
    # --- OUTSIDE pick: grab at MAIN, carry HOME, back to MAIN, release, REACH ---
    calls, state, seen = drive(protocol.NEXT_PHASE_OUTSIDE_PICK, protocol.PHASE_TO_REACH)
    check("outside", calls, state, seen, [
        protocol.PHASE_OUT_TO_MAIN, protocol.PHASE_CLOSE_GRAB,
        protocol.PHASE_BACK_TO_HOME, protocol.PHASE_OUT_TO_MAIN_2,
        protocol.PHASE_OPEN_RELEASE, protocol.PHASE_TO_REACH,
    ])
    moves = [t for (kind, t) in calls if kind == "move"]
    assert moves[:4] == [protocol.SM1_MAIN_ABS, 0, protocol.SM1_MAIN_ABS,
                         protocol.SM1_REACH_ABS], moves[:4]

    # --- TWO-JAW: HOME <-> MAIN shuttle, no REACH ---
    calls, state, seen = drive(protocol.NEXT_PHASE_TWO_JAW, protocol.PHASE_OPEN_RELEASE)
    check("twojaw", calls, state, seen, [
        protocol.PHASE_OUT_TO_MAIN, protocol.PHASE_CLOSE_GRAB,
        protocol.PHASE_BACK_TO_HOME, protocol.PHASE_OPEN_RELEASE,
    ])
    moves = [t for (kind, t) in calls if kind == "move"]
    assert moves[:2] == [protocol.SM1_MAIN_ABS, 0], moves[:2]
    assert protocol.SM1_REACH_ABS not in moves, "2-jaw must never move to REACH"

    print("OK: both demo modes verified (outside pick + 2-jaw HOME<->MAIN shuttle)")


if __name__ == "__main__":
    run()

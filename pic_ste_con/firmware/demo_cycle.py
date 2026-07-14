"""The repeating standalone demo loop, as a persisted state machine.

Phase sequence (see protocol.NEXT_PHASE for the full linear path - there is
no branch):

    HOMING
    -> OPEN_AT_HOME_1   open gripper at HOME
    -> OUT_TO_MAIN_1    move HOME -> MAIN (gripper open)
    -> BACK_TO_HOME_1   move MAIN -> HOME
    -> CLOSE_AT_HOME    close gripper at HOME
    -> OUT_TO_MAIN_2    move HOME -> MAIN (gripper closed)
    -> BACK_TO_HOME_2   move MAIN -> HOME
    -> OPEN_AT_HOME_2   open gripper at HOME
    -> CLOSE_AT_HOME_2  close gripper at HOME  (cycle_count += 1)
    -> (back to OPEN_AT_HOME_1)

HOMING drives SM1 CW into the limit switch and zeroes the step count there.
MAIN is the fixed offset protocol.SM1_MAIN_STEPS from HOME.

Every phase transition, and every completed motion chunk inside a phase, is
written to the state store before tick() returns, so DEMO PAUSE (the physical
button, the GUI, or a Pico reset) never loses more progress than "redo the
in-flight motion" - which itself resumes from its last-saved step count rather
than starting over.

The gripper CLOSE keeps StallGuard force feedback (it stops early if it feels
an object), but unlike the old pick-and-place demo, reaching CLOSED with no
object is a normal outcome here - it is not treated as a fault and does not
auto-pause the cycle.
"""

import protocol


class DemoCycle:
    def __init__(self, platform, gripper, state, persist, switch_read):
        self.platform = platform
        self.gripper = gripper
        self.state = state
        self.persist = persist
        # Callable returning True when the SM1 home limit switch is actuated;
        # main.py owns the Pin and handles active-low polarity.
        self.switch_read = switch_read

    def is_calibrated(self):
        return self.platform.is_calibrated() and self.gripper.is_calibrated()

    def start(self):
        if not self.is_calibrated():
            raise RuntimeError(
                "Set SM1_MAIN_STEPS (calibrate_main_steps.py) and calibrate SM2 "
                "OPEN/CLOSED before starting the demo"
            )
        if self.state.get("demo_phase") is None:
            self.state["demo_phase"] = protocol.PHASE_HOMING
            self.state["needs_attention"] = False
        self.state["demo_running"] = True
        self.persist()

    def pause(self):
        self.state["demo_running"] = False
        self.persist()

    def resume(self):
        if self.state.get("demo_phase") is None:
            raise RuntimeError("Nothing to resume - use DEMO START")
        if not self.is_calibrated():
            raise RuntimeError("Set SM1_MAIN_STEPS and calibrate SM2 before resuming")
        self.state["demo_running"] = True
        self.state["needs_attention"] = False
        self.persist()

    def reset(self):
        self.state["demo_running"] = False
        self.state["demo_phase"] = None
        self.state["cycle_count"] = 0
        self.state["needs_attention"] = False
        self.persist()

    def _advance(self, finished_phase):
        # One full cycle completes at the second close-at-home.
        if finished_phase == protocol.PHASE_CLOSE_AT_HOME_2:
            self.state["cycle_count"] = self.state.get("cycle_count", 0) + 1
        next_phase = protocol.NEXT_PHASE.get(finished_phase)
        if next_phase is None:
            raise RuntimeError("no defined next phase after {}".format(finished_phase))
        self.state["demo_phase"] = next_phase
        self.persist()

    def tick(self, poll_inputs):
        """Advance the demo by one step, if it is currently running.

        `poll_inputs` is invoked repeatedly during any in-progress motion so
        serial commands and the physical pause button are handled promptly
        (mid-chunk), instead of only between whole phases.
        """
        if not self.state.get("demo_running", False):
            return
        if self.state.get("needs_attention", False):
            return

        phase = self.state.get("demo_phase")
        if phase is None:
            return

        def should_pause():
            poll_inputs()
            return not self.state.get("demo_running", False)

        if phase == protocol.PHASE_HOMING:
            if self.platform.home(self.switch_read, should_pause):
                self._advance(phase)
            return

        if phase in (protocol.PHASE_OPEN_AT_HOME_1, protocol.PHASE_OPEN_AT_HOME_2):
            if self.gripper.open_gripper(should_pause):
                self._advance(phase)
            return

        if phase in (protocol.PHASE_OUT_TO_MAIN_1, protocol.PHASE_OUT_TO_MAIN_2):
            if self.platform.move_to(protocol.POSITION_MAIN, should_pause):
                self._advance(phase)
            return

        if phase in (protocol.PHASE_BACK_TO_HOME_1, protocol.PHASE_BACK_TO_HOME_2):
            if self.platform.move_to(protocol.POSITION_HOME, should_pause):
                self._advance(phase)
            return

        if phase in (protocol.PHASE_CLOSE_AT_HOME, protocol.PHASE_CLOSE_AT_HOME_2):
            # Both a real grip (True) and a full close with nothing there
            # (False) are fine; only None means "paused mid-close, retry".
            result = self.gripper.close_and_verify_grip(should_pause)
            if result is not None:
                self._advance(phase)
            return

        raise RuntimeError("unknown demo phase: {}".format(phase))

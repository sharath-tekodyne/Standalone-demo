"""The repeating standalone OUTSIDE-pick demo loop, as a persisted state machine.

Phase sequence (see protocol.NEXT_PHASE for the full linear path - there is
no branch). On boot the rig RELEASES then HOMES once, then loops the 6-phase
body:

    RELEASE          open jaws / drop any held object         (once)
    -> HOMING        find HOME on the limit switch            (once)
    -> OUT_TO_MAIN   move to MAIN (jaws open)            <-- loop body starts
    -> CLOSE_GRAB    CLOSE on the object (force feedback)
    -> BACK_TO_HOME  carry to HOME (step 0)
    -> OUT_TO_MAIN_2 carry back out to MAIN
    -> OPEN_RELEASE  OPEN fully to release
    -> TO_REACH      move to REACH (cycle_count += 1)
    -> (back to OUT_TO_MAIN)

HOMING drives SM1 CW into the limit switch and zeroes the step count there.
MAIN and REACH are FIXED absolute step targets (protocol.SM1_MAIN_ABS /
SM1_REACH_ABS), reached by move_to_absolute - no per-move calibration.

Only CLOSE_GRAB uses StallGuard force feedback: it stops early if it feels an
object, but reaching fully-shut with nothing there is a normal outcome (not a
fault). RELEASE and OPEN_RELEASE always open the jaws all the way to step 0;
opening when already open is a no-op, so RELEASE only does work when the rig
booted with something clamped in the jaws.

Every phase transition and every completed motion chunk is written to the
state store before tick() returns, so a PAUSE (button, GUI, or Pico reset)
never loses more than "redo the in-flight motion".
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
        # HOME is found by the switch and MAIN/REACH are fixed constants, so the
        # only thing that must be calibrated by hand is the gripper CLOSED cap
        # (force-feedback CLOSE needs it). OPEN is step 0.
        return self.gripper.is_calibrated()

    def start(self):
        if not self.is_calibrated():
            raise RuntimeError(
                "Calibrate the gripper CLOSED position (SM2 MARK CLOSED) before starting the demo"
            )
        # Run the platform fast during the demo (smaller half-period = faster).
        self.state["sm1_speed_us_override"] = protocol.SM1_DEMO_SPEED_US
        # IMPORTANT: do NOT override the gripper's speed / current / StallGuard
        # threshold here. The grip uses exactly what was tuned in the GUI and
        # saved to state.json (grip speed via sm2_speed_us_override, current via
        # sm2_torque, sensitivity via sm2_stallguard_threshold - all applied at
        # boot in main.py). A close that grips via "SM2 CLOSE" in the GUI then
        # behaves identically in the standalone demo. Forcing demo-specific
        # constants here is what made the two diverge.
        if self.state.get("demo_phase") is None:
            self.state["demo_phase"] = protocol.FIRST_PHASE
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
            raise RuntimeError("Calibrate the gripper CLOSED position before resuming")
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
        # One full cycle completes at the mode's end phase (REACH for the
        # outside pick, the HOME release for the 2-jaw shuttle).
        if finished_phase == protocol.CYCLE_END_PHASE:
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

        if phase == protocol.PHASE_RELEASE:
            # Boot release: force the jaws to the OPEN stop regardless of the
            # tracked count, so a gripper that powered off closed on an object
            # actually lets go (open_gripper alone would no-op if the count
            # already read 0). This also re-zeros the jaw position.
            if self.gripper.open_to_stop(should_pause):
                self._advance(phase)
            return

        if phase == protocol.PHASE_OPEN_RELEASE:
            # Mid-cycle release: the count is fresh (we just closed), so a plain
            # relative open back to step 0 is enough.
            if self.gripper.open_gripper(should_pause):
                self._advance(phase)
            return

        if phase == protocol.PHASE_HOMING:
            if self.platform.home(self.switch_read, should_pause):
                self._advance(phase)
            return

        if phase in (protocol.PHASE_OUT_TO_MAIN, protocol.PHASE_OUT_TO_MAIN_2):
            if self.platform.move_to_absolute(protocol.SM1_MAIN_ABS, should_pause):
                self._advance(phase)
            return

        if phase == protocol.PHASE_BACK_TO_HOME:
            if self.platform.move_to_absolute(0, should_pause):
                self._advance(phase)
            return

        if phase == protocol.PHASE_TO_REACH:
            if self.platform.move_to_absolute(protocol.SM1_REACH_ABS, should_pause):
                self._advance(phase)
            return

        if phase == protocol.PHASE_CLOSE_GRAB:
            # Both a real grip (True) and a full close with nothing there
            # (False) are fine; only None means "paused mid-close, retry".
            result = self.gripper.close_and_verify_grip(should_pause)
            if result is not None:
                self._advance(phase)
            return

        raise RuntimeError("unknown demo phase: {}".format(phase))

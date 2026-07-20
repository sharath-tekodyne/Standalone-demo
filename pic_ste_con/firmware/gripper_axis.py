"""SM2 - the 2-jaw gripper axis, with StallGuard-based grip verification.

Like the platform axis, jaw position is tracked open-loop in steps, with
OPEN defined as step 0 and CLOSED as a calibrated offset from there.

close_and_verify_grip() is the important one: it closes the jaws toward the
calibrated CLOSED position in small chunks and watches the TMC2209's DIAG
pin (StallGuard) after each chunk. If the jaws meet resistance before
reaching CLOSED, that resistance *is* the object - the move stops early and
this reports a successful grip. If the jaws reach fully CLOSED without ever
seeing resistance, nothing was there to grip.

All chunked motion goes through _move_toward(), which reports each chunk to
an optional `log` callback (requested/completed/stalled/position) - this is
what shows up as DBG lines on the bridge so a stall (real or false-positive)
is visible immediately instead of only after the whole move gives up.
"""

import protocol


class GripperAxis:
    def __init__(self, motor, state, persist, log=None):
        self.motor = motor
        self.state = state
        self.persist = persist
        self.log = log if callable(log) else (lambda message: None)

    def is_calibrated(self):
        return self.state.get("sm2_closed_steps") is not None

    def mark(self, name):
        """Record the current jaw position as OPEN or CLOSED."""
        if name == protocol.GRIPPER_OPEN:
            current = self.state["sm2_position_steps"]
            if self.state.get("sm2_closed_steps") is not None:
                self.state["sm2_closed_steps"] -= current
            self.state["sm2_position_steps"] = 0
            self.state["gripper_state"] = protocol.GRIPPER_OPEN
        elif name == protocol.GRIPPER_CLOSED:
            self.state["sm2_closed_steps"] = self.state["sm2_position_steps"]
            self.state["gripper_state"] = protocol.GRIPPER_CLOSED
        else:
            raise ValueError("unknown gripper position name: {}".format(name))
        self.persist()

    def _speed_us(self):
        override = self.state.get("sm2_speed_us_override")
        if override is not None:
            return override
        speed = self.state.get("sm2_speed", protocol.DEFAULT_SPEED)
        return self.motor.SPEED_PRESETS_US[speed]

    def _move_toward(self, target, should_pause, chunk=None, watch_stall=True):
        """Move toward an absolute step target in chunks.

        Returns "REACHED" (target hit), "STALLED" (StallGuard tripped - only
        possible when watch_stall=True), or "PAUSED" (should_pause interrupted).
        watch_stall=False moves without watching the DIAG pin, for opening and
        jogging where a stall is just noise; only closing needs it True.
        """
        chunk = chunk or protocol.DEFAULT_CHUNK_STEPS
        speed_us = self._speed_us()
        # Enable once up front; passing reenable=False to move_steps below avoids
        # the per-chunk 25 ms enable stall that made the motion jittery. Persist
        # only on exit (not every chunk) - per-chunk flash writes also stalled it.
        self.motor.enable()

        while True:
            current = self.state["sm2_position_steps"]
            remaining = target - current
            if remaining == 0:
                self.persist()
                return "REACHED"

            direction = self.motor.CW if remaining > 0 else self.motor.ACW
            step_count = min(chunk, abs(remaining))
            stalled, completed = self.motor.move_steps(
                direction, step_count, speed_us=speed_us, reenable=False, watch_stall=watch_stall)
            actual = completed if direction == self.motor.CW else -completed
            self.state["sm2_position_steps"] += actual

            if stalled or completed != step_count:
                self.persist()
                return "STALLED"

            if should_pause is not None and should_pause():
                self.persist()
                return "PAUSED"

    def open_gripper(self, should_pause=None):
        """Move to the calibrated OPEN position (step 0). Returns True once open.

        Opening does NOT watch StallGuard - the jaws are just returning to a
        known position, so a DIAG blip must not abort it (that produced false
        'stalled while opening' errors). Only closing watches for a grip.
        """
        result = self._move_toward(0, should_pause, watch_stall=False)
        if result == "PAUSED":
            return False  # paused mid-move
        self.state["gripper_state"] = protocol.GRIPPER_OPEN
        self.persist()
        return True

    def close_and_verify_grip(self, should_pause=None):
        """Close toward CLOSED, watching for StallGuard resistance.

        Returns True if an object was gripped (stalled before reaching
        CLOSED), False if the jaws reached CLOSED with nothing gripped, or
        None if should_pause() interrupted the attempt partway through.
        """
        if self.state.get("sm2_closed_steps") is None:
            raise RuntimeError("Gripper CLOSED position is not calibrated yet - use SM2 MARK CLOSED first")

        if not protocol.GRIPPER_FORCE_FEEDBACK:
            return self._close_to_position()   # open-loop, no force sensing

        # Force-feedback grip. Drive PAST the fully-shut position (over-travel)
        # so the motor is FORCED to jam - on the object (early) or on the jaws'
        # hard stop (at full) - and StallGuard trips in either case. Classify by
        # WHERE it stopped: stalling >= SM2_GRIP_MARGIN steps short of fully-shut
        # means an object was held; stalling ~at full means the jaws just closed.
        full = self.state["sm2_closed_steps"]
        current = self.state["sm2_position_steps"]
        remaining = full - current
        direction = self.motor.CW if remaining >= 0 else self.motor.ACW
        command = abs(remaining) + protocol.SM2_GRIP_OVERTRAVEL
        stalled, completed = self.motor.move_steps(
            direction, command, speed_us=protocol.SM2_GRIP_SPEED_US, watch_stall=True)
        actual = completed if direction == self.motor.CW else -completed
        self.state["sm2_position_steps"] += actual
        self.state["gripper_state"] = protocol.GRIPPER_CLOSED
        self.persist()

        gap = full - self.state["sm2_position_steps"]           # >0 = stopped short of full
        gripped = stalled and gap >= protocol.SM2_GRIP_MARGIN
        self.log("SM2 close stalled={} pos={} gap={} gripped={}".format(
            int(stalled), self.state["sm2_position_steps"], gap, int(gripped)))
        return True if gripped else False

    def open_and_verify_grip(self, should_pause=None, max_steps=None):
        """Force-feedback OPEN: expand the jaws (open direction) while watching
        StallGuard, stopping the instant they meet resistance - used to grip a
        test tube from the INSIDE (the 4-jaw demo, step 8).

        Searches up to max_steps in the open (ACW) direction. Returns True if
        StallGuard tripped within that (an object was felt/held), False if the
        jaws opened the whole way without touching anything. `should_pause` is
        accepted for a consistent call signature but a force-open is a single
        committed move, so it is not polled mid-stroke.
        """
        if max_steps is None:
            max_steps = protocol.SM2_OPEN_GRIP_MAX

        if not protocol.GRIPPER_FORCE_FEEDBACK:
            # No force sensing configured - fall back to a plain open, report nothing.
            self.open_gripper(should_pause)
            return False

        self.motor.enable()
        stalled, completed = self.motor.move_steps(
            self.motor.ACW, int(max_steps), speed_us=protocol.SM2_GRIP_SPEED_US, watch_stall=True)
        # Opening is ACW, so position decreases by the steps actually taken.
        self.state["sm2_position_steps"] -= completed
        self.state["gripper_state"] = protocol.GRIPPER_OPEN
        self.persist()
        self.log("SM2 opengrip stalled={} pos={} completed={} gripped={}".format(
            int(stalled), self.state["sm2_position_steps"], completed, int(stalled)))
        return True if stalled else False

    def _close_to_position(self):
        """Open-loop close to the calibrated CLOSED position (no StallGuard)."""
        remaining = self.state["sm2_closed_steps"] - self.state["sm2_position_steps"]
        if remaining != 0:
            direction = self.motor.CW if remaining > 0 else self.motor.ACW
            _, completed = self.motor.move_steps(
                direction, abs(remaining), speed_us=self._speed_us(), watch_stall=False)
            self.state["sm2_position_steps"] += completed if direction == self.motor.CW else -completed
        self.state["gripper_state"] = protocol.GRIPPER_CLOSED
        self.persist()
        return False

    def goto_steps(self, target_steps, should_pause=None):
        """Manual test move to an arbitrary absolute jaw position (not OPEN/CLOSED specifically)."""
        result = self._move_toward(int(target_steps), should_pause, watch_stall=False)
        if result != "PAUSED":
            self.state["gripper_state"] = protocol.GRIPPER_UNKNOWN
            self.persist()
        return result

    def sg_probe(self, steps, sample_every=20):
        """Diagnostic: move `steps` in the CLOSE direction, sampling the live
        StallGuard load (SG_RESULT) every `sample_every` steps. Returns
        (sg_min, samples). Run it empty and with an object to see how much the
        load drops - the threshold*2 should sit between the two.
        """
        speed_us = self._speed_us()
        self.motor.enable()
        self.motor.set_direction(self.motor.CW)   # CW = close direction
        sg_min = 1023
        samples = []
        for i in range(int(steps)):
            self.motor.pulse(speed_us)
            self.state["sm2_position_steps"] += 1
            if i % sample_every == 0:
                try:
                    sg = self.motor.read_stallguard()
                except Exception:
                    sg = -1
                samples.append(sg)
                if 0 <= sg < sg_min:
                    sg_min = sg
        self.state["gripper_state"] = protocol.GRIPPER_UNKNOWN
        self.persist()
        return sg_min, samples

    def jog(self, direction, steps):
        """Manual test move - used by the GUI's manual panel to feel out OPEN/CLOSED."""
        speed_us = self._speed_us()
        # jogging is manual positioning - don't let StallGuard abort it early
        stalled, completed = self.motor.move_steps(direction, steps, speed_us=speed_us, watch_stall=False)
        delta = completed if direction == self.motor.CW else -completed
        self.state["sm2_position_steps"] += delta
        self.state["gripper_state"] = protocol.GRIPPER_UNKNOWN
        self.persist()
        self.log(
            "SM2 jog dir={} requested={} completed={} stalled={} position={}".format(
                direction, steps, completed, int(stalled), self.state["sm2_position_steps"]
            )
        )
        return stalled, completed

    def stop(self):
        self.motor.disable()

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

    def _move_toward(self, target, should_pause, chunk=None):
        """Move toward an absolute step target in chunks.

        Returns "REACHED" (target hit, no resistance), "STALLED" (StallGuard
        tripped, or a chunk otherwise came up short), or "PAUSED"
        (should_pause() interrupted the attempt).
        """
        chunk = chunk or protocol.DEFAULT_CHUNK_STEPS
        speed_us = self._speed_us()

        while True:
            current = self.state["sm2_position_steps"]
            remaining = target - current
            if remaining == 0:
                return "REACHED"

            direction = self.motor.CW if remaining > 0 else self.motor.ACW
            step_count = min(chunk, abs(remaining))
            stalled, completed = self.motor.move_steps(direction, step_count, speed_us=speed_us)
            actual = completed if direction == self.motor.CW else -completed
            self.state["sm2_position_steps"] += actual
            self.persist()

            self.log(
                "SM2 chunk dir={} requested={} completed={} stalled={} position={} target={}".format(
                    direction, step_count, completed, int(stalled), self.state["sm2_position_steps"], target
                )
            )

            if stalled or completed != step_count:
                return "STALLED"

            if should_pause is not None and should_pause():
                return "PAUSED"

    def open_gripper(self, should_pause=None):
        """Move back to the calibrated OPEN position. Returns True once fully open."""
        result = self._move_toward(0, should_pause)

        if result == "REACHED":
            self.state["gripper_state"] = protocol.GRIPPER_OPEN
            self.persist()
            return True

        if result == "STALLED":
            self.state["gripper_state"] = protocol.GRIPPER_UNKNOWN
            self.persist()
            raise RuntimeError(
                "SM2 stalled while opening (position={}, target=0, sgthrs={}) - check that OPEN was "
                "calibrated at the true mechanical limit, or lower the StallGuard threshold".format(
                    self.state["sm2_position_steps"], self.state.get("sm2_stallguard_threshold")
                )
            )

        return False  # paused mid-move

    def close_and_verify_grip(self, should_pause=None):
        """Close toward CLOSED, watching for StallGuard resistance.

        Returns True if an object was gripped (stalled before reaching
        CLOSED), False if the jaws reached CLOSED with nothing gripped, or
        None if should_pause() interrupted the attempt partway through.
        """
        if self.state.get("sm2_closed_steps") is None:
            raise RuntimeError("Gripper CLOSED position is not calibrated yet - use SM2 MARK CLOSED first")

        result = self._move_toward(self.state["sm2_closed_steps"], should_pause)

        if result == "REACHED":
            self.state["gripper_state"] = protocol.GRIPPER_CLOSED
            self.persist()
            return False

        if result == "STALLED":
            self.state["gripper_state"] = protocol.GRIPPER_CLOSED
            self.persist()
            return True

        return None  # paused mid-attempt

    def goto_steps(self, target_steps, should_pause=None):
        """Manual test move to an arbitrary absolute jaw position (not OPEN/CLOSED specifically)."""
        result = self._move_toward(int(target_steps), should_pause)
        if result != "PAUSED":
            self.state["gripper_state"] = protocol.GRIPPER_UNKNOWN
            self.persist()
        return result

    def jog(self, direction, steps):
        """Manual test move - used by the GUI's manual panel to feel out OPEN/CLOSED."""
        speed_us = self._speed_us()
        stalled, completed = self.motor.move_steps(direction, steps, speed_us=speed_us)
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

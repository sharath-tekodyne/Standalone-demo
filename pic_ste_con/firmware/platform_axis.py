"""SM1 - the platform axis that carries the gripper between HOME and MAIN.

HOME is found physically: home() drives CW into a limit switch and zeroes the
step count there. MAIN is a fixed step offset from HOME (protocol.SM1_MAIN_STEPS),
measured once with firmware/calibrate_main_steps.py.

Away from the switch, position is tracked open-loop: every completed step is
added to (or subtracted from) `sm1_position_steps` in the shared state dict.
The limit switch re-zeroes that count on every home(), so open-loop drift is
cancelled each time the axis re-homes rather than accumulating forever.

Motion is chunked (protocol.DEFAULT_CHUNK_STEPS at a time) so a paused demo
takes effect within roughly one chunk's travel time instead of waiting for
an entire HOME<->MAIN move to finish. Each chunk is reported to an optional
`log` callback (requested/completed/position) for debugging.
"""

import protocol


class PlatformAxis:
    def __init__(self, motor, state, persist, log=None):
        self.motor = motor
        self.state = state
        self.persist = persist
        self.log = log if callable(log) else (lambda message: None)

    def _main_steps(self):
        """HOME->MAIN distance as a POSITIVE magnitude of steps.

        Prefers the runtime-calibrated value (SM1 MARK MAIN / SM1 SET MAINSTEPS)
        and falls back to protocol.SM1_MAIN_STEPS. abs() so a stray sign can't
        flip the direction - MAIN direction is applied in target_steps(). None
        if neither is set (treated as "not calibrated yet").
        """
        saved = self.state.get("sm1_main_steps")
        if saved:
            return abs(saved)
        if protocol.SM1_MAIN_STEPS:
            return abs(protocol.SM1_MAIN_STEPS)
        return None

    def is_calibrated(self):
        # HOME needs no calibration - it is found live by the limit switch. The
        # axis is "calibrated" once the HOME->MAIN distance is known.
        return self._main_steps() is not None

    def _clear_switch(self, switch_read, speed_us):
        """If the switch is already actuated when homing starts, back off (ACW)
        until it releases, plus a small margin, so the approach that follows
        always drives IN from clear and zeros at the same repeatable point.

        Without this, a switch that already reads actuated (carriage resting on
        it, a stray reading, or power lost mid-home) makes _approach_switch
        return TRIPPED with no motion - a false "home" that never touched the
        switch. Raises if it never clears (stuck switch or wrong polarity).
        """
        if not switch_read():
            return
        self.motor.set_direction(self.motor.ACW)
        steps = 0
        while switch_read():
            self.motor.pulse(speed_us)
            steps += 1
            if steps >= protocol.HOMING_MAX_STEPS:
                raise RuntimeError(
                    "SM1 homing failed: limit switch still reads actuated after backing off "
                    "{} steps - check HOME_SWITCH_ACTIVE_LOW and that the switch isn't stuck".format(steps)
                )
        for _ in range(protocol.HOMING_BACKOFF_STEPS):   # extra margin clear of the release point
            self.motor.pulse(speed_us)

    def _approach_switch(self, switch_read, speed_us, should_pause):
        """Step CW until the limit switch reports active.

        Returns "TRIPPED" once the switch is active, or "PAUSED" if
        should_pause() interrupted first. Raises if the switch never trips
        within HOMING_MAX_STEPS (a broken/unwired switch, or the wrong
        HOME_SWITCH_ACTIVE_LOW polarity).
        """
        self.motor.set_direction(self.motor.CW)
        start_us = protocol.HOMING_START_US
        ramp = protocol.HOMING_RAMP_STEPS
        steps = 0
        while True:
            if switch_read():
                return "TRIPPED"
            # Accelerate from a slow start up to the target speed so the motor
            # doesn't stall the instant it's asked to move at full homing speed.
            if steps < ramp and start_us > speed_us:
                cur_us = start_us - (start_us - speed_us) * steps // ramp
            else:
                cur_us = speed_us
            self.motor.pulse(cur_us)
            steps += 1
            if steps >= protocol.HOMING_MAX_STEPS:
                raise RuntimeError(
                    "SM1 homing failed: limit switch never tripped after {} steps - "
                    "check the switch wiring and protocol.HOME_SWITCH_ACTIVE_LOW".format(steps)
                )
            if should_pause is not None and should_pause():
                return "PAUSED"

    def home(self, switch_read, should_pause=None):
        """Drive CW into the limit switch to establish HOME (step 0).

        Two-stage for a repeatable zero: a fast approach until the switch
        first trips, a fixed back-off clear of it, then a slow re-approach.
        `switch_read` is a callable returning True when the switch is actuated
        (main.py owns the Pin and handles active-low polarity).

        Returns True once homed, or False if should_pause() interrupted the
        attempt (the caller should keep the HOMING phase so a resume re-homes
        from scratch - homing is idempotent).
        """
        self.motor.enable()

        # Always start clear of the switch so the approach below genuinely drives
        # into it (no false immediate-trip "home").
        self._clear_switch(switch_read, protocol.HOMING_SLOW_US)

        if self._approach_switch(switch_read, protocol.HOMING_SPEED_US, should_pause) == "PAUSED":
            return False

        # Back off clear of the switch so the slow re-approach has room.
        self.motor.set_direction(self.motor.ACW)
        for _ in range(protocol.HOMING_BACKOFF_STEPS):
            self.motor.pulse(protocol.HOMING_SPEED_US)

        if self._approach_switch(switch_read, protocol.HOMING_SLOW_US, should_pause) == "PAUSED":
            return False

        self.state["sm1_position_steps"] = 0
        self.persist()
        self.log("SM1 homed: limit switch tripped, position zeroed")
        return True

    def mark(self, name):
        """Record HOME or MAIN at the current physical position.

        MARK HOME zeroes the step count here (the recording zero used by the
        GUI's MAIN calibration, and a fallback re-home). MARK MAIN records the
        current count as the persisted HOME->MAIN distance - so jog to HOME,
        MARK HOME, jog to MAIN, MARK MAIN.
        """
        if name == protocol.POSITION_HOME:
            self.state["sm1_position_steps"] = 0
            self.persist()
        elif name == protocol.POSITION_MAIN:
            pos = self.state["sm1_position_steps"]
            if pos == 0:
                raise RuntimeError(
                    "MAIN cannot be HOME (0) - jog SM1 away from HOME before saving MAIN"
                )
            # store the magnitude; MAIN's ACW direction is applied in target_steps()
            self.state["sm1_main_steps"] = abs(pos)
            self.persist()
        else:
            raise ValueError("SM1 MARK only supports HOME or MAIN")

    def target_steps(self, name):
        if name == protocol.POSITION_HOME:
            return 0
        if name == protocol.POSITION_MAIN:
            steps = self._main_steps()
            if steps is None:
                raise RuntimeError(
                    "MAIN is not calibrated - jog to MAIN and MARK MAIN, or set "
                    "protocol.SM1_MAIN_STEPS (calibrate_main_steps.py)"
                )
            # MAIN is ACW of HOME, and ACW is the negative direction (HOME=0 at
            # the CW switch), so the absolute target is negative.
            return -steps
        raise ValueError("unknown position name: {}".format(name))

    def _speed_us(self):
        override = self.state.get("sm1_speed_us_override")
        if override is not None:
            return override
        speed = self.state.get("sm1_speed", protocol.DEFAULT_SPEED)
        torque = self.state.get("sm1_torque", protocol.DEFAULT_TORQUE)
        profile = self.motor.TORQUE_PRESETS[torque]
        return max(100, min(self.motor.SPEED_PRESETS_US[speed], profile["run_limit_us"]))

    def move_to_absolute(self, target, should_pause=None):
        """Move toward an absolute step count, pulsing continuously for smooth
        motion (the same way homing does).

        Returns True once the target is reached, or False if should_pause()
        returned True partway through (caller keeps its phase so a retry
        continues from here).

        Why not motor.move_steps() per chunk: that re-enables the driver every
        chunk (a 25 ms sleep) and we used to flash-persist every chunk too -
        both stalled the motor periodically and made the motion jittery. Here
        we enable once, pulse straight through, only check should_pause between
        chunks, and only persist on pause / completion.
        """
        speed_us = self._speed_us()
        chunk = protocol.DEFAULT_CHUNK_STEPS
        self.motor.enable()

        while True:
            current = self.state["sm1_position_steps"]
            remaining = target - current
            if remaining == 0:
                self.persist()
                return True

            direction = self.motor.CW if remaining > 0 else self.motor.ACW
            self.motor.set_direction(direction)
            step_count = min(chunk, abs(remaining))
            delta = 1 if direction == self.motor.CW else -1
            for _ in range(step_count):
                self.motor.pulse(speed_us)
                self.state["sm1_position_steps"] += delta

            if should_pause is not None and should_pause():
                self.persist()
                return False

    def move_to(self, name, should_pause=None):
        """Move toward a named calibrated position (HOME/A/B). See move_to_absolute()."""
        return self.move_to_absolute(self.target_steps(name), should_pause)

    def jog(self, direction, steps):
        """Manual test move - not calibration-aware, used by the GUI's manual panel."""
        override = self.state.get("sm1_speed_us_override")
        if override is not None:
            completed = self.motor.move_steps(direction, steps, override)
        else:
            speed = self.state.get("sm1_speed", protocol.DEFAULT_SPEED)
            torque = self.state.get("sm1_torque", protocol.DEFAULT_TORQUE)
            completed = self.motor.move_with_presets(direction=direction, steps=steps, speed=speed, torque=torque)
        delta = completed if direction == self.motor.CW else -completed
        self.state["sm1_position_steps"] += delta
        self.persist()
        self.log("SM1 jog dir={} requested={} completed={} position={}".format(direction, steps, completed, self.state["sm1_position_steps"]))
        return completed

    def stop(self):
        self.motor.disable()

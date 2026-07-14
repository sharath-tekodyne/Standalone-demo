try:
    from machine import Pin  # type: ignore[import-not-found]
except ImportError:
    Pin = None
import time


class TMC2208:
    """STEP/DIR/EN-only TMC2208 driver (standalone mode, no UART)."""

    SPEED_PRESETS_US = {
        "LOW": 1400,
        "MEDIUM": 900,
        "HIGH": 450,
    }

    # Without UART current control, torque is approximated by motion profile.
    TORQUE_PRESETS = {
        "LOW": {"start_us": 1800, "ramp_steps": 80, "run_limit_us": 1200},
        "MEDIUM": {"start_us": 1400, "ramp_steps": 160, "run_limit_us": 900},
        "HIGH": {"start_us": 1100, "ramp_steps": 260, "run_limit_us": 600},
    }

    CW = 1
    ACW = 0

    def __init__(self, step_pin=19, dir_pin=20, en_pin=18):
        if Pin is None:
            raise RuntimeError("machine.Pin is only available on MicroPython/Pico")
        self.step_out = Pin(step_pin, Pin.OUT)
        self.dir_out = Pin(dir_pin, Pin.OUT)
        self.en_out = Pin(en_pin, Pin.OUT)

        self.current_direction = self.CW
        self.speed_preset = "MEDIUM"
        self.torque_preset = "MEDIUM"

        self.step_out.value(0)
        self.dir_out.value(0)
        self.disable()

    def enable(self):
        # TMC2208 EN is active-low on common modules.
        self.en_out.value(0)
        time.sleep_ms(25)

    def disable(self):
        self.en_out.value(1)

    def set_direction(self, direction):
        if direction not in (self.ACW, self.CW):
            raise ValueError("direction must be 0 (ACW) or 1 (CW)")
        self.current_direction = int(direction)
        self.dir_out.value(self.current_direction)

    def set_cw(self):
        self.set_direction(self.CW)

    def set_acw(self):
        self.set_direction(self.ACW)

    def set_speed_preset(self, level):
        level = str(level).upper().strip()
        if level not in self.SPEED_PRESETS_US:
            raise ValueError("speed level must be LOW/MEDIUM/HIGH")
        self.speed_preset = level

    def set_torque_preset(self, level):
        level = str(level).upper().strip()
        if level not in self.TORQUE_PRESETS:
            raise ValueError("torque level must be LOW/MEDIUM/HIGH")
        self.torque_preset = level

    def pulse(self, half_period_us):
        half_period_us = int(half_period_us)
        if half_period_us < 100:
            raise ValueError("half_period_us too low, minimum is 100")
        self.step_out.value(1)
        time.sleep_us(half_period_us)
        self.step_out.value(0)
        time.sleep_us(half_period_us)

    def move_steps(self, direction, steps, speed_us=600):
        if direction not in (self.ACW, self.CW):
            raise ValueError("direction must be 0 or 1")
        if int(steps) <= 0:
            raise ValueError("steps must be greater than 0")

        self.enable()
        self.set_direction(direction)

        completed = 0
        try:
            for _ in range(int(steps)):
                self.pulse(speed_us)
                completed += 1
        finally:
            self.step_out.value(0)

        return completed

    def move_steps_ramped(self, direction, steps, start_us=1500, end_us=600, ramp_steps=200):
        if direction not in (self.ACW, self.CW):
            raise ValueError("direction must be 0 or 1")
        if int(steps) <= 0:
            raise ValueError("steps must be greater than 0")

        start_us = int(start_us)
        end_us = int(end_us)
        if start_us < end_us:
            raise ValueError("start_us must be >= end_us")

        steps = int(steps)
        ramp = min(int(ramp_steps), steps // 2)
        cruise = steps - (2 * ramp)

        self.enable()
        self.set_direction(direction)

        completed = 0
        try:
            if ramp > 0:
                delta = (start_us - end_us) / ramp
                for i in range(ramp):
                    self.pulse(start_us - (delta * i))
                    completed += 1

            for _ in range(cruise):
                self.pulse(end_us)
                completed += 1

            if ramp > 0:
                delta = (start_us - end_us) / ramp
                for i in range(ramp):
                    self.pulse(end_us + (delta * i))
                    completed += 1
        finally:
            self.step_out.value(0)

        return completed

    def move_with_presets(self, direction, steps, speed=None, torque=None):
        """Move using LOW/MEDIUM/HIGH speed and LOW/MEDIUM/HIGH torque presets."""
        speed = self.speed_preset if speed is None else str(speed).upper().strip()
        torque = self.torque_preset if torque is None else str(torque).upper().strip()

        self.set_speed_preset(speed)
        self.set_torque_preset(torque)

        profile = self.TORQUE_PRESETS[torque]
        run_us = max(100, min(self.SPEED_PRESETS_US[speed], profile["run_limit_us"]))

        return self.move_steps_ramped(
            direction=direction,
            steps=steps,
            start_us=profile["start_us"],
            end_us=run_us,
            ramp_steps=profile["ramp_steps"],
        )

    def run_chunk(self, direction, chunk_steps=80, speed=None, torque=None):
        """Run a short chunk so higher-level code can remain responsive."""
        speed = self.speed_preset if speed is None else str(speed).upper().strip()
        torque = self.torque_preset if torque is None else str(torque).upper().strip()

        self.set_speed_preset(speed)
        self.set_torque_preset(torque)

        self.enable()
        self.set_direction(direction)

        half_period = max(100, min(self.SPEED_PRESETS_US[speed], self.TORQUE_PRESETS[torque]["run_limit_us"]))

        completed = 0
        try:
            for _ in range(int(chunk_steps)):
                self.pulse(half_period)
                completed += 1
        finally:
            self.step_out.value(0)

        return completed

    def run_continuous(self, direction, speed=None, torque=None, chunk_steps=80, should_stop=None):
        """
        Continuous run using repeated chunks until should_stop() is True.

        should_stop: callable returning bool, checked after every chunk.
        """
        should_stop = should_stop if callable(should_stop) else (lambda: False)
        total = 0
        while not should_stop():
            total += self.run_chunk(direction, chunk_steps=chunk_steps, speed=speed, torque=torque)
        return total

    def jog(self, direction, revolutions, speed_us=600, steps_per_rev=1600):
        total_steps = int(revolutions * steps_per_rev)
        return self.move_steps(direction, total_steps, speed_us)

    def nudge(self, direction, steps=200, speed_us=600):
        return self.move_steps(direction, steps, speed_us)

"""TMC2209 driver for the Pico: STEP/DIR/EN motion plus UART-configured
StallGuard, used as the gripper axis (SM2).

StallGuard is what gives the demo its "force feedback": once the jaws meet
resistance from a gripped object, the DIAG pin goes high mid-move. move_steps()
below detects that and returns early instead of running the full requested
step count, which is exactly how gripper_axis.py tells "gripped" from
"nothing there".
"""

from machine import Pin, UART
import time


class UARTCommunicationError(Exception):
    pass


class HardwareTimeoutError(Exception):
    pass


class TMC2209:
    CW = 1
    ACW = 0

    SPEED_PRESETS_US = {
        "LOW": 1400,
        "MEDIUM": 900,
        "HIGH": 450,
    }

    # (ihold, irun, iholddelay) written into the IHOLD_IRUN register (0x10).
    # Higher irun = more jaw force before StallGuard trips; if the gripper
    # crushes soft objects, drop a level, if it never detects a grip on firm
    # objects, raise one.
    CURRENT_PRESETS = {
        "LOW": (4, 8, 6),
        "MEDIUM": (8, 16, 6),
        "HIGH": (12, 24, 4),
    }

    def __init__(self, step_pin, dir_pin, en_pin, diag_pin, uart_id, tx_pin, rx_pin, baudrate=115200,
                 invert_dir=False):
        self.uart = UART(uart_id, baudrate=baudrate, tx=Pin(tx_pin), rx=Pin(rx_pin), timeout=20)
        self.step_out = Pin(step_pin, Pin.OUT)
        self.dir_out = Pin(dir_pin, Pin.OUT)
        self.en_out = Pin(en_pin, Pin.OUT)
        self.diag_in = Pin(diag_pin, Pin.IN, Pin.PULL_DOWN)
        # If the motor coils are wired reversed, invert_dir flips the DIR pin so
        # logical CW/ACW still map to physical CW/ACW (position tracking unchanged).
        self.invert_dir = bool(invert_dir)

        self.current_direction = self.CW
        self.speed_preset = "MEDIUM"
        self.torque_preset = "MEDIUM"
        self.stallguard_threshold = 80

        self.step_out.value(0)
        self.dir_out.value(0)
        self.disable()

    def enable(self):
        self.en_out.value(0)
        time.sleep_ms(25)

    def disable(self):
        self.en_out.value(1)

    def set_direction(self, direction):
        if direction not in (self.ACW, self.CW):
            raise ValueError("direction must be 0 (ACW) or 1 (CW)")
        self.current_direction = int(direction)
        out = self.current_direction ^ 1 if self.invert_dir else self.current_direction
        self.dir_out.value(out)

    def set_speed_preset(self, level):
        level = str(level).upper().strip()
        if level not in self.SPEED_PRESETS_US:
            raise ValueError("speed level must be LOW/MEDIUM/HIGH")
        self.speed_preset = level

    def set_torque_preset(self, level):
        level = str(level).upper().strip()
        if level not in self.CURRENT_PRESETS:
            raise ValueError("torque level must be LOW/MEDIUM/HIGH")
        self.torque_preset = level
        ihold, irun, delay = self.CURRENT_PRESETS[level]
        self.configure_current(ihold, irun, delay)

    def _calc_crc(self, datagram):
        crc = 0
        for byte in datagram:
            current_byte = byte
            for _ in range(8):
                if (crc >> 7) ^ (current_byte & 0x01):
                    crc = ((crc << 1) ^ 0x07) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
                current_byte >>= 1
        return crc

    def read_register(self, reg):
        while self.uart.any():
            self.uart.read()
        req = bytearray([0x05, 0x00, reg & 0x7F, 0x00])
        req[3] = self._calc_crc(req[:3])
        self.uart.write(req)
        time.sleep_ms(10)

        if self.uart.any() == 0:
            raise HardwareTimeoutError("TMC2209 UART did not respond - check wiring/power.")
        raw_data = self.uart.read()
        if len(raw_data) < 12:
            raise UARTCommunicationError("Malformed UART reply from TMC2209.")

        reply = raw_data[4:12]
        if self._calc_crc(reply[:7]) != reply[7]:
            raise UARTCommunicationError("UART reply failed CRC check (electrical noise).")

        return (reply[3] << 24) | (reply[4] << 16) | (reply[5] << 8) | reply[6]

    def write_register(self, reg, data):
        data = int(data)
        datagram = bytearray([0x05, 0x00, reg | 0x80, (data >> 24) & 0xFF, (data >> 16) & 0xFF, (data >> 8) & 0xFF, data & 0xFF])
        datagram.append(self._calc_crc(datagram))
        self.uart.write(datagram)
        time.sleep_ms(5)

    def configure_current(self, ihold, irun, iholddelay):
        register_value = (ihold & 0x1F) | ((irun & 0x1F) << 8) | ((iholddelay & 0x0F) << 16)
        self.write_register(0x10, register_value)

    def configure_stallguard(self, threshold):
        if not (0 <= threshold <= 255):
            raise ValueError("StallGuard threshold must be between 0 and 255.")
        self.stallguard_threshold = int(threshold)
        self.write_register(0x00, 0x00000000)   # GCONF=0: StealthChop (StallGuard4 runs in StealthChop)
        self.write_register(0x14, 0xFFFFF)       # TCOOLTHRS (0x14): route DIAG to StallGuard at all speeds
        self.write_register(0x40, self.stallguard_threshold)  # SGTHRS (higher = MORE sensitive on TMC2209)

    def pulse(self, half_period_us):
        half_period_us = int(half_period_us)
        if half_period_us < 100:
            half_period_us = 100
        self.step_out.value(1)
        time.sleep_us(half_period_us)
        self.step_out.value(0)
        time.sleep_us(half_period_us)

    def read_stallguard(self):
        """Live StallGuard load, SG_RESULT (reg 0x41), ~0..510: LOWER = MORE load.
        DIAG trips when this drops to SGTHRS*2 or below. Only meaningful while
        the motor is actually moving.
        """
        return self.read_register(0x41) & 0x03FF

    def move_steps(self, direction, steps, speed_us=600, blinding_window=150, reenable=True, watch_stall=True):
        """Move up to `steps` pulses, aborting early if StallGuard trips.

        Returns (stalled, steps_taken). `stalled=True` with steps_taken <
        `steps` means the jaws met resistance before finishing the move -
        that is a successful grip. `stalled=False` with steps_taken ==
        `steps` means the move completed with nothing in the way.

        reenable=False skips the enable() (a 25 ms sleep). Chunked callers
        enable once up front and pass reenable=False so the motor doesn't stall
        for 25 ms between chunks - that stall made multi-chunk moves jittery.

        watch_stall=False ignores the DIAG/StallGuard pin entirely - used for
        opening and jogging, where a "stall" is just motion noise and must not
        abort the move. Only closing (grip detection) needs watch_stall=True.
        """
        if direction not in (0, 1):
            raise ValueError("direction must be 0 or 1")
        if steps <= 0:
            raise ValueError("steps must be greater than 0")
        if speed_us < 100:
            raise ValueError("speed_us too fast, minimum is 100us")

        if reenable:
            self.enable()
        self.set_direction(direction)

        steps_taken = 0
        stalled = False

        # Ignore StallGuard for the first few steps of every call: current
        # ramp-up can look like a stall to the DIAG pin otherwise.
        adaptive_window = max(10, min(blinding_window, int(steps * 0.25)))

        for _ in range(int(steps)):
            if watch_stall and steps_taken > adaptive_window:
                if self.diag_in.value() == 1:
                    time.sleep_us(10)
                    if self.diag_in.value() == 1:
                        stalled = True
                        break

            self.step_out.value(1)
            time.sleep_us(int(speed_us))
            self.step_out.value(0)
            time.sleep_us(int(speed_us))
            steps_taken += 1

        return stalled, steps_taken

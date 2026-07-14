from machine import Pin, UART
import time

# --- CUSTOM EXCEPTIONS (Rule 7) ---
class UARTCommunicationError(Exception): pass
class HardwareTimeoutError(Exception): pass

class TMC2209:
    def __init__(self, tx_pin, rx_pin, step_pin, dir_pin, en_pin, diag_pin, baudrate=115200, timeout_ms=20):
        self.uart = UART(0, baudrate=baudrate, tx=Pin(tx_pin), rx=Pin(rx_pin), timeout=timeout_ms)
        self.step_out = Pin(step_pin, Pin.OUT)
        self.dir_out = Pin(dir_pin, Pin.OUT)
        self.en_out = Pin(en_pin, Pin.OUT)
        self.diag_in = Pin(diag_pin, Pin.IN, Pin.PULL_DOWN)
        
        self.disable()

    def disable(self):
        self.en_out.value(1)

    def enable(self):
        self.en_out.value(0)
        time.sleep(0.05)

    def _calc_crc(self, datagram):
        crc = 0
        for byte in datagram:
            current_byte = byte
            for _ in range(8):
                if (crc >> 7) ^ (current_byte & 0x01): crc = ((crc << 1) ^ 0x07) & 0xFF
                else: crc = (crc << 1) & 0xFF
                current_byte >>= 1
        return crc

    def read_register(self, reg):
        while self.uart.any(): self.uart.read()
        req = bytearray([0x05, 0x00, reg & 0x7F, 0x00])
        req[3] = self._calc_crc(req[:3])
        self.uart.write(req)
        time.sleep_ms(10)
        
        if self.uart.any() == 0: raise HardwareTimeoutError("Driver offline.")
        raw_data = self.uart.read()
        if len(raw_data) < 12: raise UARTCommunicationError("Malformed packet.")
        
        reply = raw_data[4:12]
        if self._calc_crc(reply[:7]) != reply[7]: raise UARTCommunicationError("EMI DETECTED!")
            
        return (reply[3] << 24) | (reply[4] << 16) | (reply[5] << 8) | reply[6]

    def write_register(self, reg, data):
        data = int(data) # Guarantee integer format
        datagram = bytearray([0x05, 0x00, reg | 0x80, (data >> 24) & 0xFF, (data >> 16) & 0xFF, (data >> 8) & 0xFF, data & 0xFF])
        datagram.append(self._calc_crc(datagram))
        self.uart.write(datagram)
        time.sleep_ms(5)

    def configure_stallguard(self, threshold, current_config):
        if not (0 <= threshold <= 255):
            raise ValueError("StallGuard threshold must be between 0 and 255.")
        self.read_register(0x00) 
        self.write_register(0x00, 0x00000000) 
        self.write_register(0x14, 0xFFFFF)    
        self.write_register(0x40, threshold)  
        self.write_register(0x10, current_config) 

    def move_steps(self, direction, steps, speed_us=600, blinding_window=150):
        # RULE 7: Pre-actuation parameter validation
        if direction not in [0, 1]: raise ValueError("Direction must be 0 or 1")
        if steps <= 0: raise ValueError("Steps must be greater than 0")
        if speed_us < 100: raise ValueError("Speed_us too fast. Minimum is 100us.")
        
        self.enable()
        self.dir_out.value(direction)
        
        steps_taken = 0
        stalled = False

        # LOGIC: Ensure we always check for stalls after at least 10 steps, 
        # or 25% of the total move for mid-sized jogs.
        adaptive_window = max(10, min(blinding_window, int(steps * 0.25)))

        for _ in range(int(steps)):
            if steps_taken > adaptive_window:
                # If DIAG is high, check twice more to filter vibration noise
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

        # Strict SOC: Firmware reports absolute truth. No artificial 0-step returns.
        return stalled, steps_taken
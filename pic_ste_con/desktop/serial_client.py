"""Non-blocking USB serial client for talking to the Pico bridge."""

from __future__ import annotations

import queue
import threading

try:
    import serial
    from serial.tools import list_ports
except Exception:
    serial = None
    list_ports = None

PY_SERIAL_STATUS = (
    "pyserial available"
    if serial is not None
    else r"pyserial missing: run .\.venv\Scripts\python.exe -m pip install pyserial"
)

DEFAULT_BAUD = 115200


def looks_like_pico(port_info):
    text = " ".join(
        str(value or "")
        for value in (port_info["device"], port_info["description"], port_info["hwid"])
    ).lower()
    return "pico" in text or "rp2" in text or "rpi-rp2" in text or port_info["vid"] == 0x2E8A


class SerialClient:
    """Owns the serial port and a background reader thread.

    Reads land in `rx_queue`; the GUI polls that queue on the Tk main
    thread instead of touching Tk widgets from the reader thread.
    """

    def __init__(self):
        self.ser = None
        self.reader_thread = None
        self.reader_running = False
        self.rx_queue = queue.Queue()

    def list_ports(self):
        if list_ports is None:
            return []
        ports = []
        for port in list_ports.comports():
            ports.append(
                {
                    "device": port.device,
                    "description": port.description or "",
                    "hwid": port.hwid or "",
                    "vid": port.vid,
                    "pid": port.pid,
                }
            )
        return ports

    def connect(self, port, baudrate=DEFAULT_BAUD):
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        self.ser = serial.Serial(port=port, baudrate=int(baudrate), timeout=0.2, write_timeout=0.5)
        self.reader_running = True
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

    def disconnect(self):
        self.reader_running = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def is_connected(self):
        return self.ser is not None and self.ser.is_open

    def send_line(self, line):
        if not self.is_connected():
            raise RuntimeError("Not connected")
        self.ser.write((line.strip() + "\n").encode("utf-8"))

    def _reader_loop(self):
        while self.reader_running and self.ser and self.ser.is_open:
            try:
                raw = self.ser.readline()
                if raw:
                    self.rx_queue.put(raw.decode("utf-8", errors="replace").strip())
            except Exception as exc:
                self.rx_queue.put(f"ERR reader {exc}")
                break

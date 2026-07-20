"""USB-serial transport for the Pico bridge - pure I/O, no GUI knowledge.

A background thread reads bytes, splits them into newline-terminated lines,
and pushes ("line", text) tuples onto a thread-safe queue that the GUI drains
on its own (Tk) thread. Disconnects/read errors are surfaced as
("error", message) on the same queue so the UI can react without the reader
thread ever touching Tk.

Kept deliberately small: open/close/is_open/send + list_ports. The
request/reply correlation (send_expect) lives in the app, where the Tk timer
for timeouts lives - that keeps every user-facing callback on the GUI thread.
"""

import queue
import threading
import time

try:
    import serial
    from serial.tools import list_ports
    IMPORT_ERROR = None
except ImportError as exc:  # surfaced by the app so the user gets a clear hint
    serial = None
    list_ports = None
    IMPORT_ERROR = str(exc)

DEFAULT_BAUD = 115200


class SerialLink:
    def __init__(self):
        self._ser = None
        self._reader = None
        self._stop = threading.Event()
        self._buf = b""
        self.rx_queue = queue.Queue()

    @staticmethod
    def available():
        return serial is not None

    @staticmethod
    def list_ports():
        if list_ports is None:
            return []
        return [(p.device, (p.description or "")) for p in list_ports.comports()]

    def is_open(self):
        return self._ser is not None and getattr(self._ser, "is_open", False)

    def open(self, port, baud=DEFAULT_BAUD):
        if serial is None:
            raise RuntimeError("pyserial is not installed (pip install pyserial)")
        if self.is_open():
            self.close()
        # short read timeout so the reader loop stays responsive to _stop
        self._ser = serial.Serial(port, baud, timeout=0.1)
        self._buf = b""
        self._stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def close(self):
        self._stop.set()
        reader = self._reader
        if reader is not None and reader.is_alive():
            reader.join(timeout=1.0)
        self._reader = None
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def send(self, line):
        if not self.is_open():
            raise RuntimeError("serial port is not open")
        payload = (line.rstrip("\r\n") + "\n").encode("utf-8", "replace")
        self._ser.write(payload)

    def _read_loop(self):
        while not self._stop.is_set():
            try:
                chunk = self._ser.read(256)
            except Exception as exc:
                self.rx_queue.put(("error", str(exc)))
                return
            if not chunk:
                time.sleep(0.005)
                continue
            self._buf += chunk
            while b"\n" in self._buf:
                raw, self._buf = self._buf.split(b"\n", 1)
                text = raw.decode("utf-8", "replace").rstrip("\r")
                if text:
                    self.rx_queue.put(("line", text))

"""Desktop GUI for controlling a Pico 2W running MicroPython over USB serial.

The desktop app runs on regular Python on Windows. The Pico must run
main_tmc2208.py on the Pico.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import ttkbootstrap as ttk
try:
    from ttkbootstrap.widgets.scrolled import ScrolledText
except ImportError:
    from ttkbootstrap.scrolled import ScrolledText

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
PORT_REFRESH_MS = 2500
HEARTBEAT_MS = 7000
PICO_BOOT_WAIT_MS = 800
LOG_DIR = Path(__file__).with_name("logs")
LOG_DIR.mkdir(exist_ok=True)


class SessionLogger:
    def __init__(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = LOG_DIR / f"session_{timestamp}.md"
        self.lines = []
        self._write_header()

    def _write_header(self):
        self.write("# Pico TMC2208 Session Report")
        self.write("")
        self.write(f"- Started: {datetime.now().isoformat(timespec='seconds')}")
        self.write(f"- Host: Windows GUI")
        self.write("")

    def write(self, line):
        self.lines.append(line)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def snapshot(self, title, fields):
        self.write(f"## {title}")
        for key, value in fields.items():
            self.write(f"- {key}: {value}")
        self.write("")

    def footer(self):
        self.write(f"- Updated: {datetime.now().isoformat(timespec='seconds')}")

    def export_text(self):
        return "\n".join(self.lines)


def _looks_like_pico(port_info):
    text = " ".join(
        str(value or "")
        for value in (
            port_info["device"],
            port_info["description"],
            port_info["hwid"],
        )
    ).lower()
    return "pico" in text or "rp2" in text or "rpi-rp2" in text or port_info["vid"] == 0x2E8A


class PicoSerialClient:
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
        self.ser = serial.Serial(
            port=port,
            baudrate=int(baudrate),
            timeout=0.2,
            write_timeout=0.5,
        )
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


class MotorControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Pico 2W TMC2208 Controller")
        self.root.geometry("1040x760")
        self.root.minsize(900, 680)

        self.client = PicoSerialClient()
        self.running = False
        self.port_map = {}
        self.auto_connect_attempted = False
        self.auto_connected = False
        self.session = SessionLogger()
        self.last_rx_line = ""
        self.last_tx_line = ""

        self.port_var = tk.StringVar(value="")
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        self.direction_var = tk.StringVar(value="CW")
        self.speed_var = tk.StringVar(value="MEDIUM")
        self.torque_var = tk.StringVar(value="MEDIUM")
        self.move_steps_var = tk.StringVar(value="1600")
        self.jog_steps_var = tk.StringVar(value="200")
        self.chunk_steps_var = tk.StringVar(value="120")
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.auto_scroll_var = tk.BooleanVar(value=True)
        self.auto_connect_var = tk.BooleanVar(value=True)
        self.debug_var = tk.BooleanVar(value=True)
        self.command_var = tk.StringVar(value="")

        self.presets = {
            "Fine": {"direction": "CW", "speed": "LOW", "torque": "LOW", "move": 200, "jog": 100, "chunk": 60},
            "Balanced": {"direction": "CW", "speed": "MEDIUM", "torque": "MEDIUM", "move": 800, "jog": 200, "chunk": 120},
            "Fast": {"direction": "CW", "speed": "HIGH", "torque": "HIGH", "move": 1600, "jog": 400, "chunk": 180},
            "Safe": {"direction": "CW", "speed": "LOW", "torque": "MEDIUM", "move": 300, "jog": 120, "chunk": 80},
        }

        self.status_var = tk.StringVar(value="Ready")
        self.port_status_var = tk.StringVar(value="Scanning ports")
        self.mode_var = tk.StringVar(value="Idle")
        self.session_path_var = tk.StringVar(value=str(self.session.path))
        self.log_text = None

        self._build_ui()
        self._schedule_tasks()
        self._refresh_ports()
        self._set_connected_state(False)
        self._log_event("APP", f"Session log: {self.session.path}")

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(5, weight=1)

        style = ttk.Style()
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))

        banner = ttk.Frame(self.root)
        banner.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")
        banner.columnconfigure(0, weight=1)
        ttk.Label(banner, text="Pico 2W TMC2208 Controller", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(banner, text="STEP / DIR / EN serial control with live session logging").grid(
            row=1, column=0, sticky="w"
        )

        connection = ttk.LabelFrame(self.root, text="Connection")
        connection.grid(row=1, column=0, padx=12, pady=10, sticky="ew")
        for col in range(8):
            connection.columnconfigure(col, weight=1 if col in (1, 4, 6) else 0)

        ttk.Label(connection, text="Serial Port").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        self.port_combo = ttk.Combobox(connection, textvariable=self.port_var, values=[], state="readonly", width=36)
        self.port_combo.grid(row=0, column=1, padx=8, pady=8, sticky="w")

        ttk.Button(connection, text="Refresh", command=self._refresh_ports).grid(row=0, column=2, padx=8, pady=8)
        ttk.Checkbutton(connection, text="Auto-refresh", variable=self.auto_refresh_var).grid(row=0, column=3, padx=8, pady=8)

        ttk.Label(connection, text="Baud").grid(row=0, column=4, padx=8, pady=8, sticky="w")
        ttk.Entry(connection, textvariable=self.baud_var, width=10).grid(row=0, column=5, padx=8, pady=8, sticky="w")

        self.connect_btn = ttk.Button(connection, text="Connect", command=self.connect)
        self.connect_btn.grid(row=0, column=6, padx=8, pady=8)

        self.disconnect_btn = ttk.Button(connection, text="Disconnect", command=self.disconnect, state="disabled")
        self.disconnect_btn.grid(row=0, column=7, padx=8, pady=8)

        ttk.Label(connection, textvariable=self.session_path_var, wraplength=900).grid(
            row=1, column=0, columnspan=8, padx=8, pady=(0, 8), sticky="w"
        )

        motion = ttk.LabelFrame(self.root, text="Motion")
        motion.grid(row=2, column=0, padx=12, pady=8, sticky="ew")
        for col in range(8):
            motion.columnconfigure(col, weight=1 if col in (1, 3, 5, 7) else 0)

        ttk.Label(motion, text="Direction").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        ttk.Combobox(motion, textvariable=self.direction_var, values=["CW", "ACW"], state="readonly", width=10).grid(
            row=0, column=1, padx=8, pady=8, sticky="w"
        )

        ttk.Label(motion, text="Speed").grid(row=0, column=2, padx=8, pady=8, sticky="w")
        ttk.Combobox(motion, textvariable=self.speed_var, values=["LOW", "MEDIUM", "HIGH"], state="normal", width=12).grid(
            row=0, column=3, padx=8, pady=8, sticky="w"
        )

        ttk.Label(motion, text="Torque").grid(row=0, column=4, padx=8, pady=8, sticky="w")
        ttk.Combobox(motion, textvariable=self.torque_var, values=["LOW", "MEDIUM", "HIGH"], state="normal", width=12).grid(
            row=0, column=5, padx=8, pady=8, sticky="w"
        )

        ttk.Label(motion, text="Move steps").grid(row=1, column=0, padx=8, pady=8, sticky="w")
        ttk.Entry(motion, textvariable=self.move_steps_var, width=14).grid(row=1, column=1, padx=8, pady=8, sticky="w")

        ttk.Label(motion, text="Jog steps").grid(row=1, column=2, padx=8, pady=8, sticky="w")
        ttk.Entry(motion, textvariable=self.jog_steps_var, width=14).grid(row=1, column=3, padx=8, pady=8, sticky="w")

        ttk.Label(motion, text="Chunk steps").grid(row=1, column=4, padx=8, pady=8, sticky="w")
        ttk.Entry(motion, textvariable=self.chunk_steps_var, width=14).grid(row=1, column=5, padx=8, pady=8, sticky="w")

        actions = ttk.Frame(motion)
        actions.grid(row=2, column=0, columnspan=8, padx=8, pady=10, sticky="ew")

        self.hold_btn = ttk.Button(actions, text="Hold", command=self.hold_motor, state="disabled")
        self.hold_btn.grid(row=0, column=0, padx=5)

        self.release_btn = ttk.Button(actions, text="Release", command=self.release_motor, state="disabled")
        self.release_btn.grid(row=0, column=1, padx=5)

        self.enable_btn = ttk.Button(actions, text="Enable", command=self.hold_motor, state="disabled")
        self.enable_btn.grid(row=0, column=2, padx=5)

        self.disable_btn = ttk.Button(actions, text="Disable", command=self.release_motor, state="disabled")
        self.disable_btn.grid(row=0, column=3, padx=5)

        self.move_btn = ttk.Button(actions, text="Move", command=self.move_steps, state="disabled")
        self.move_btn.grid(row=0, column=4, padx=5)

        self.left_btn = ttk.Button(actions, text="Jog ACW", command=lambda: self.jog("ACW"), state="disabled")
        self.left_btn.grid(row=0, column=5, padx=5)

        self.right_btn = ttk.Button(actions, text="Jog CW", command=lambda: self.jog("CW"), state="disabled")
        self.right_btn.grid(row=0, column=6, padx=5)

        self.start_btn = ttk.Button(actions, text="Start Continuous", command=self.start_continuous, state="disabled")
        self.start_btn.grid(row=1, column=0, padx=5, pady=6)

        self.stop_btn = ttk.Button(actions, text="Stop", command=self.stop_continuous, state="disabled")
        self.stop_btn.grid(row=1, column=1, padx=5, pady=6)

        self.estop_btn = ttk.Button(actions, text="EMERGENCY STOP", command=self.emergency_stop, state="disabled")
        self.estop_btn.grid(row=1, column=2, padx=5, pady=6)

        self.status_btn = ttk.Button(actions, text="Status", command=self.query_status, state="disabled")
        self.status_btn.grid(row=1, column=3, padx=5, pady=6)

        self.ping_btn = ttk.Button(actions, text="Ping", command=self.ping, state="disabled")
        self.ping_btn.grid(row=1, column=4, padx=5, pady=6)

        self.self_test_btn = ttk.Button(actions, text="Self Test", command=self.run_self_test, state="disabled")
        self.self_test_btn.grid(row=1, column=5, padx=5, pady=6)

        self.help_btn = ttk.Button(actions, text="Bridge Help", command=self.bridge_help, state="disabled")
        self.help_btn.grid(row=1, column=6, padx=5, pady=6)

        self.stats_btn = ttk.Button(actions, text="Diagnostics", command=self.request_diagnostics, state="disabled")
        self.stats_btn.grid(row=1, column=7, padx=5, pady=6)

        ttk.Checkbutton(actions, text="Bridge debug", variable=self.debug_var, command=self.set_bridge_debug).grid(
            row=2, column=0, columnspan=2, padx=8, pady=6, sticky="w"
        )
        ttk.Checkbutton(actions, text="Auto-scroll log", variable=self.auto_scroll_var).grid(
            row=2, column=2, columnspan=2, padx=8, pady=6, sticky="w"
        )
        ttk.Checkbutton(actions, text="Auto-connect", variable=self.auto_connect_var).grid(
            row=2, column=4, columnspan=2, padx=8, pady=6, sticky="w"
        )
        ttk.Label(actions, text="Manual command").grid(row=2, column=6, padx=(8, 2), pady=6, sticky="e")
        self.command_entry = ttk.Entry(actions, textvariable=self.command_var, width=26)
        self.command_entry.grid(row=2, column=7, padx=(2, 5), pady=6, sticky="ew")
        self.command_entry.bind("<Return>", lambda _event: self.send_manual_command())
        self.send_btn = ttk.Button(actions, text="Send", command=self.send_manual_command, state="disabled")
        self.send_btn.grid(row=2, column=8, padx=5, pady=6)

        preset_bar = ttk.LabelFrame(self.root, text="Motion Presets")
        preset_bar.grid(row=3, column=0, padx=12, pady=8, sticky="ew")
        preset_bar.columnconfigure(0, weight=1)

        preset_buttons = ttk.Frame(preset_bar)
        preset_buttons.grid(row=0, column=0, padx=8, pady=8, sticky="w")

        ttk.Button(preset_buttons, text="Fine", command=lambda: self.apply_preset("Fine")).grid(row=0, column=0, padx=5)
        ttk.Button(preset_buttons, text="Balanced", command=lambda: self.apply_preset("Balanced")).grid(row=0, column=1, padx=5)
        ttk.Button(preset_buttons, text="Fast", command=lambda: self.apply_preset("Fast")).grid(row=0, column=2, padx=5)
        ttk.Button(preset_buttons, text="Safe", command=lambda: self.apply_preset("Safe")).grid(row=0, column=3, padx=5)

        status_box = ttk.LabelFrame(self.root, text="Status")
        status_box.grid(row=4, column=0, padx=12, pady=8, sticky="ew")
        status_box.columnconfigure(0, weight=1)

        ttk.Label(status_box, textvariable=self.status_var, anchor="w", style="Status.TLabel").grid(
            row=0, column=0, padx=8, pady=6, sticky="ew"
        )
        ttk.Label(status_box, textvariable=self.port_status_var, anchor="w").grid(row=1, column=0, padx=8, pady=6, sticky="ew")
        ttk.Label(status_box, textvariable=self.mode_var, anchor="w").grid(row=2, column=0, padx=8, pady=6, sticky="ew")

        log_box = ttk.LabelFrame(self.root, text="Pico Console")
        log_box.grid(row=5, column=0, padx=12, pady=8, sticky="nsew")
        log_box.rowconfigure(0, weight=1)
        log_box.columnconfigure(0, weight=1)

        self.log_text = ScrolledText(log_box, height=16, wrap="word", autohide=True)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        bottom = ttk.Frame(self.root)
        bottom.grid(row=6, column=0, padx=12, pady=4, sticky="ew")
        bottom.columnconfigure(0, weight=1)

        ttk.Label(bottom, text=PY_SERIAL_STATUS).grid(row=0, column=0, sticky="w")
        ttk.Label(bottom, text="Run main_tmc2208.py from Thonny before connecting (this filename does not auto-run on boot).").grid(
            row=1, column=0, sticky="w"
        )

        ttk.Button(bottom, text="Save Report Now", command=self.save_report).grid(row=0, column=1, rowspan=2, padx=8, sticky="e")

    def _schedule_tasks(self):
        self._poll_rx_queue()
        self._auto_refresh_ports()
        self._heartbeat_check()

    def _append_log(self, line):
        self.log_text.text.config(state="normal")
        self.log_text.insert("end", line + "\n")
        if self.auto_scroll_var.get():
            self.log_text.see("end")
        self.log_text.text.config(state="disabled")
        self.session.write(line)

    def _log_event(self, kind, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.session.write(f"[{stamp}] {kind}: {message}")

    def _set_status(self, text):
        self.status_var.set(text)

    def _set_port_status(self, text):
        self.port_status_var.set(text)

    def _refresh_ports(self):
        ports = self.client.list_ports()
        self.port_map = {port["device"]: port for port in ports}
        labels = [port["device"] for port in ports]
        self.port_combo["values"] = labels

        if not ports:
            self.port_var.set("")
            self._set_port_status("No serial ports found")
            return

        if self.port_var.get() not in self.port_map:
            preferred = next((port["device"] for port in ports if _looks_like_pico(port)), labels[0])
            self.port_var.set(preferred)

        self._set_port_status(f"{len(ports)} serial port(s) available")

        if self.auto_connect_var.get() and not self.auto_connected and not self.client.is_connected() and len(labels) == 1:
            self.auto_connected = True
            self.root.after(250, self.connect)

    def _auto_refresh_ports(self):
        if self.auto_refresh_var.get() and not self.client.is_connected():
            self._refresh_ports()
        self.root.after(PORT_REFRESH_MS, self._auto_refresh_ports)

    def _set_connected_state(self, connected):
        self.connect_btn.state(["disabled"] if connected else ["!disabled"])
        self.disconnect_btn.state(["!disabled"] if connected else ["disabled"])

        btn_state = ["!disabled"] if connected else ["disabled"]
        for widget in (
            self.hold_btn,
            self.release_btn,
            self.enable_btn,
            self.disable_btn,
            self.move_btn,
            self.left_btn,
            self.right_btn,
            self.start_btn,
            self.estop_btn,
            self.status_btn,
            self.ping_btn,
            self.self_test_btn,
            self.help_btn,
            self.stats_btn,
            self.send_btn,
        ):
            widget.state(btn_state)
        self.stop_btn.state(["disabled"])

    def _validate_int(self, value, label, minimum=1):
        try:
            parsed = int(str(value).strip())
        except Exception:
            raise ValueError(f"{label} must be a whole number")
        if parsed < minimum:
            raise ValueError(f"{label} must be at least {minimum}")
        return parsed

    def apply_preset(self, preset_name):
        preset = self.presets[preset_name]
        self.direction_var.set(preset["direction"])
        self.speed_var.set(preset["speed"])
        self.torque_var.set(preset["torque"])
        self.move_steps_var.set(str(preset["move"]))
        self.jog_steps_var.set(str(preset["jog"]))
        self.chunk_steps_var.set(str(preset["chunk"]))
        self.mode_var.set(f"Preset: {preset_name}")
        self._set_status(f"Applied {preset_name} preset")
        self._append_log(f"> preset {preset_name}")

    def _selected_port(self):
        return self.port_var.get().strip()

    def connect(self):
        port = self._selected_port()
        if not port:
            messagebox.showerror("Connect Error", "Select a serial port")
            return
        try:
            baud = self._validate_int(self.baud_var.get(), "Baud", minimum=1200)
            self._log_event("TX", f"connect {port} {baud}")
            self.client.connect(port=port, baudrate=baud)
            self._set_connected_state(True)
            self._set_status(f"Connected to {port} @ {baud}; waiting for Pico bridge")
            self._append_log(f"> connected {port} {baud}")
            # Opening a Pico USB serial port can reset its MicroPython program.
            # Delay the first commands so the bridge has time to print READY.
            self.root.after(PICO_BOOT_WAIT_MS, self._initial_bridge_check)
        except Exception as exc:
            self._set_status("Connection failed")
            self._log_event("ERR", f"connect failed: {exc}")
            messagebox.showerror("Connect Error", str(exc))

    def _initial_bridge_check(self):
        if not self.client.is_connected():
            return
        self.ping()
        self.query_status()

    def disconnect(self):
        self.running = False
        self.client.disconnect()
        self._set_connected_state(False)
        self._set_status("Disconnected")
        self.mode_var.set("Idle")
        self._append_log("> disconnected")
        self._log_event("APP", "Disconnected")
        self.session.footer()

    def _send(self, cmd):
        self.last_tx_line = cmd
        self.client.send_line(cmd)
        self._append_log(f"> {cmd}")
        self._log_event("TX", cmd)

    def ping(self):
        try:
            self._send("PING")
        except Exception as exc:
            messagebox.showerror("Ping Error", str(exc))

    def bridge_help(self):
        try:
            self._send("HELP")
            self._set_status("Requested bridge command help")
        except Exception as exc:
            messagebox.showerror("Bridge Help Error", str(exc))

    def request_diagnostics(self):
        try:
            self._send("STATS")
            self._set_status("Requested Pico diagnostics")
        except Exception as exc:
            messagebox.showerror("Diagnostics Error", str(exc))

    def set_bridge_debug(self):
        if not self.client.is_connected():
            return
        try:
            self._send("DEBUG {}".format("ON" if self.debug_var.get() else "OFF"))
        except Exception as exc:
            self._log_event("ERR", f"Debug setting failed: {exc}")
            messagebox.showerror("Debug Error", str(exc))

    def send_manual_command(self):
        command = self.command_var.get().strip()
        if not command:
            return
        try:
            self._send(command)
            self.command_var.set("")
            self._set_status("Manual command sent")
        except Exception as exc:
            self._log_event("ERR", f"Manual command failed: {exc}")
            messagebox.showerror("Manual Command Error", str(exc))

    def query_status(self):
        try:
            self._send("STATUS")
        except Exception as exc:
            messagebox.showerror("Status Error", str(exc))

    def run_self_test(self):
        if not self.client.is_connected():
            messagebox.showerror("Self Test Error", "Connect to the Pico first")
            return

        def worker():
            try:
                self._log_event("APP", "Self test started")
                commands = [
                    "PING",
                    "STATUS",
                    "SET DIR CW",
                    "SET SPEED LOW",
                    "SET TORQUE MEDIUM",
                    "ENABLE",
                    "MOVE 20",
                    "DISABLE",
                ]
                for command in commands:
                    self._send(command)
                    time.sleep(0.2)
                self.root.after(0, lambda: self._set_status("Self test commands sent"))
                self._log_event("APP", "Self test completed")
            except Exception as exc:
                self._log_event("ERR", f"Self test failed: {exc}")
                self.root.after(0, lambda: messagebox.showerror("Self Test Error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def emergency_stop(self):
        try:
            if self.client.is_connected():
                self._send("ESTOP")
            self.running = False
            self.stop_btn.state(["disabled"])
            self.start_btn.state(["!disabled"] if self.client.is_connected() else ["disabled"])
            self.mode_var.set("Emergency stop")
            self._set_status("Emergency stop sent")
        except Exception as exc:
            self._log_event("ERR", f"ESTOP failed: {exc}")
            messagebox.showerror("Emergency Stop Error", str(exc))

    def hold_motor(self):
        try:
            self._send("ENABLE")
            self._set_status("Driver enabled")
            self.mode_var.set("Holding")
        except Exception as exc:
            self._log_event("ERR", f"Hold failed: {exc}")
            messagebox.showerror("Hold Error", str(exc))

    def release_motor(self):
        try:
            self.stop_continuous()
            self._send("DISABLE")
            self._set_status("Driver disabled")
            self.mode_var.set("Released")
        except Exception as exc:
            self._log_event("ERR", f"Release failed: {exc}")
            messagebox.showerror("Release Error", str(exc))

    def _sync_profile(self, direction=None):
        direction = self.direction_var.get().upper().strip() if direction is None else direction.upper().strip()
        speed = self.speed_var.get().upper().strip()
        torque = self.torque_var.get().upper().strip()
        self._send(f"SET DIR {direction}")
        self._send(f"SET SPEED {speed}")
        self._send(f"SET TORQUE {torque}")

    def move_steps(self):
        try:
            steps = self._validate_int(self.move_steps_var.get(), "Move steps")
            self._sync_profile()
            self._send(f"MOVE {steps}")
            self.mode_var.set("Move")
            self._set_status(f"Move command sent for {steps} steps")
        except Exception as exc:
            self._log_event("ERR", f"Move failed: {exc}")
            messagebox.showerror("Move Error", str(exc))

    def jog(self, direction):
        try:
            steps = self._validate_int(self.jog_steps_var.get(), "Jog steps")
            self.direction_var.set(direction)
            self._sync_profile(direction=direction)
            self._send(f"MOVE {steps}")
            self.mode_var.set(f"Jog {direction}")
            self._set_status(f"Jog {direction} sent")
        except Exception as exc:
            self._log_event("ERR", f"Jog failed: {exc}")
            messagebox.showerror("Jog Error", str(exc))

    def start_continuous(self):
        if self.running:
            return
        try:
            chunk_steps = self._validate_int(self.chunk_steps_var.get(), "Chunk steps")
            self._sync_profile()
            self._send(f"SET CHUNK {chunk_steps}")
            self._send("START")
            self.running = True
            self.start_btn.state(["disabled"])
            self.stop_btn.state(["!disabled"])
            self.mode_var.set("Continuous")
            self._set_status("Continuous run started")
        except Exception as exc:
            self._log_event("ERR", f"Start continuous failed: {exc}")
            messagebox.showerror("Start Error", str(exc))

    def stop_continuous(self):
        if not self.client.is_connected():
            return
        try:
            self._send("STOP")
        except Exception:
            pass
        self.running = False
        self.start_btn.state(["!disabled"] if self.client.is_connected() else ["disabled"])
        self.stop_btn.state(["disabled"])
        self.mode_var.set("Idle")
        self._set_status("Continuous run stopped")

    def _heartbeat_check(self):
        if self.client.is_connected():
            try:
                self._send("STATUS")
            except Exception:
                pass
        self.root.after(HEARTBEAT_MS, self._heartbeat_check)

    def _handle_line(self, line):
        self.last_rx_line = line
        self._append_log(line)
        self._log_event("RX", line)
        if line.startswith("ERR"):
            self._set_status(line)
            return

        if line.startswith("OK PONG"):
            self._set_status("Pico reachable")
            return

        if line.startswith("OK DEBUG"):
            self.debug_var.set(line.endswith("ON"))
            self._set_status(line[3:].strip())
            return

        if line.startswith("OK STATUS"):
            self._set_status(line[3:].strip())
            return

        if line.startswith("OK STOP"):
            self.running = False
            self.start_btn.state(["!disabled"] if self.client.is_connected() else ["disabled"])
            self.stop_btn.state(["disabled"])
            self.mode_var.set("Idle")
            self._set_status("Continuous run stopped")
            return

        if line.startswith("OK ESTOP"):
            self.running = False
            self.start_btn.state(["!disabled"] if self.client.is_connected() else ["disabled"])
            self.stop_btn.state(["disabled"])
            self.mode_var.set("Emergency stop")
            self._set_status("Emergency stop confirmed")
            return

        if line.startswith("OK ENABLE"):
            self.mode_var.set("Holding")
            self._set_status("Driver enabled")
            return

        if line.startswith("OK DISABLE"):
            self.mode_var.set("Released")
            self._set_status("Driver disabled")
            return

        if line.startswith("OK START"):
            self.mode_var.set("Continuous")
            self._set_status("Continuous mode armed")
            return

        if line.startswith("OK MOVE"):
            self.mode_var.set("Move complete")
            self._set_status(line[3:].strip())
            return

    def save_report(self):
        try:
            self.session.snapshot(
                "Current State",
                {
                    "Port": self._selected_port() or "(none)",
                    "Baud": self.baud_var.get(),
                    "Direction": self.direction_var.get(),
                    "Speed": self.speed_var.get(),
                    "Torque": self.torque_var.get(),
                    "Move steps": self.move_steps_var.get(),
                    "Jog steps": self.jog_steps_var.get(),
                    "Chunk steps": self.chunk_steps_var.get(),
                    "Connected": self.client.is_connected(),
                    "Running": self.running,
                    "Last TX": self.last_tx_line or "(none)",
                    "Last RX": self.last_rx_line or "(none)",
                },
            )
            self._set_status(f"Report saved to {self.session.path}")
            self._append_log(f"> report saved: {self.session.path}")
        except Exception as exc:
            self._log_event("ERR", f"report save failed: {exc}")
            messagebox.showerror("Report Error", str(exc))

    def _poll_rx_queue(self):
        try:
            while True:
                self._handle_line(self.client.rx_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._poll_rx_queue)


def main():
    root = ttk.Window(themename="superhero")
    app = MotorControlApp(root)

    def on_close():
        try:
            app.stop_continuous()
            app.disconnect()
        finally:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()

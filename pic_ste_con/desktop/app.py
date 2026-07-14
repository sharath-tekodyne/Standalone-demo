"""Main GUI window: wires together the connection, panels, and console log.

Each panel (desktop/panels/*.py) is a self-contained ttk.Frame that receives
this app instance and uses app.send()/app.log()/app state variables to talk
to the Pico bridge and reflect its status - the panels never touch the
serial port directly.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

import ttkbootstrap as ttk

try:
    from ttkbootstrap.widgets.scrolled import ScrolledText
except ImportError:
    from ttkbootstrap.scrolled import ScrolledText

import protocol
from desktop.serial_client import DEFAULT_BAUD, PY_SERIAL_STATUS, SerialClient, looks_like_pico
from desktop.session_logger import SessionLogger
from desktop.panels.connection_panel import ConnectionPanel
from desktop.panels.manual_panel import ManualPanel
from desktop.panels.calibration_panel import CalibrationPanel
from desktop.panels.demo_panel import DemoPanel
from desktop.panels.diagnostics_panel import DiagnosticsPanel
from desktop.panels.step_panel import StepPanel

PORT_REFRESH_MS = 2500
HEARTBEAT_MS = 1000
PICO_BOOT_WAIT_MS = 800


def _parse_status_fields(line):
    """Turn 'OK STATUS key=value key=value ...' into a plain dict of strings."""
    body = line.split(" ", 2)[-1] if line.upper().startswith("OK STATUS") else line
    fields = {}
    for token in body.split():
        if "=" in token:
            key, _, value = token.partition("=")
            fields[key] = value
    return fields


class MotorControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Gripper Demo Controller - SM1 (platform) / SM2 (gripper)")
        self.root.geometry("1180x860")
        self.root.minsize(1000, 760)

        self.client = SerialClient()
        self.session = SessionLogger()
        self.port_map = {}
        self.auto_connected = False
        self.last_rx_line = ""
        self.last_tx_line = ""
        self.panels = []
        # Heartbeat STATUS polls are sent silently (see send()/_handle_line()) so
        # the console/log isn't flooded with an identical line every second;
        # this counts how many silent-STATUS replies are still in flight.
        self._silent_status_pending = 0
        # One-shot waiters for send_expect(): each correlates a command with its
        # OK/ERR reply so callers (e.g. the Step-by-Step panel) learn the exact
        # outcome, with a timeout if the Pico never answers.
        self._response_waiters = []

        self.port_var = tk.StringVar(value="")
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.auto_connect_var = tk.BooleanVar(value=True)
        self.auto_scroll_var = tk.BooleanVar(value=True)
        self.debug_var = tk.BooleanVar(value=True)

        # Live status mirrors of the bridge's STATUS reply.
        self.status_fields = {}
        self.sm1_pos_var = tk.StringVar(value="?")
        self.sm1_main_var = tk.StringVar(value="not set")
        self.home_switch_var = tk.StringVar(value="?")
        self.pause_btn_var = tk.StringVar(value="?")
        self.sm2_pos_var = tk.StringVar(value="?")
        self.sm2_closed_var = tk.StringVar(value="not calibrated")
        self.gripper_state_var = tk.StringVar(value="UNKNOWN")
        self.demo_phase_var = tk.StringVar(value="(not started)")
        self.demo_running_var = tk.StringVar(value="stopped")
        self.needs_attention_var = tk.BooleanVar(value=False)
        self.cycle_count_var = tk.StringVar(value="0")
        self.sm2_ready_var = tk.StringVar(value="unknown")
        self.sm1_enabled_var = tk.StringVar(value="DISABLED")
        self.sm2_enabled_var = tk.StringVar(value="DISABLED")
        self.sm1_speed_us_var = tk.StringVar(value="AUTO")
        self.sm2_speed_us_var = tk.StringVar(value="AUTO")

        self.status_var = tk.StringVar(value="Ready")
        self.port_status_var = tk.StringVar(value="Scanning ports")
        self.session_path_var = tk.StringVar(value=str(self.session.path))
        self.log_text = None

        self._build_ui()
        self._schedule_tasks()
        self._refresh_ports()
        self._set_connected_state(False)
        self.log_event("APP", f"Session log: {self.session.path}")

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(3, weight=1)

        banner = ttk.Frame(self.root)
        banner.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="ew")
        ttk.Label(banner, text="Gripper Demo Controller", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(banner, text="SM1 platform axis (TMC2208) + SM2 gripper axis (TMC2209, StallGuard force feedback)").grid(
            row=1, column=0, sticky="w"
        )

        self.connection_panel = ConnectionPanel(self.root, self)
        self.connection_panel.grid(row=1, column=0, padx=12, pady=8, sticky="ew")

        notebook = ttk.Notebook(self.root)
        notebook.grid(row=2, column=0, padx=12, pady=6, sticky="ew")

        self.manual_panel = ManualPanel(notebook, self)
        self.calibration_panel = CalibrationPanel(notebook, self)
        self.step_panel = StepPanel(notebook, self)
        self.demo_panel = DemoPanel(notebook, self)
        self.diagnostics_panel = DiagnosticsPanel(notebook, self)

        notebook.add(self.manual_panel, text="Manual Control")
        notebook.add(self.calibration_panel, text="Calibration")
        notebook.add(self.step_panel, text="Step-by-Step")
        notebook.add(self.demo_panel, text="Demo Cycle")
        notebook.add(self.diagnostics_panel, text="Diagnostics")

        self.panels = [
            self.manual_panel,
            self.calibration_panel,
            self.step_panel,
            self.demo_panel,
            self.diagnostics_panel,
        ]

        log_box = ttk.LabelFrame(self.root, text="Pico Console")
        log_box.grid(row=3, column=0, padx=12, pady=8, sticky="nsew")
        log_box.rowconfigure(0, weight=1)
        log_box.columnconfigure(0, weight=1)
        self.log_text = ScrolledText(log_box, height=14, wrap="word", autohide=True)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.log_text.text.tag_configure("err", foreground="#ff6b6b")
        self.log_text.text.tag_configure("tx", foreground="#6ec6ff")

        bottom = ttk.Frame(self.root)
        bottom.grid(row=4, column=0, padx=12, pady=(0, 10), sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var, anchor="w").grid(row=0, column=0, sticky="w")
        ttk.Label(bottom, text=PY_SERIAL_STATUS).grid(row=1, column=0, sticky="w")
        ttk.Button(bottom, text="Save Report Now", command=self.save_report).grid(row=0, column=1, rowspan=2, padx=8, sticky="e")

    def _schedule_tasks(self):
        self._poll_rx_queue()
        self._auto_refresh_ports()
        self._heartbeat()

    # ------------------------------------------------------------ Logging

    def clear_console(self):
        self.log_text.text.config(state="normal")
        self.log_text.text.delete("1.0", "end")
        self.log_text.text.config(state="disabled")

    def append_log(self, line):
        tags = ("err",) if line.startswith("ERR") else (("tx",) if line.startswith(">") else ())
        self.log_text.text.config(state="normal")
        self.log_text.text.insert("end", line + "\n", *tags)
        if self.auto_scroll_var.get():
            self.log_text.see("end")
        self.log_text.text.config(state="disabled")
        self.session.write(line)

    def log_event(self, kind, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.session.write(f"[{stamp}] {kind}: {message}")

    def set_status(self, text):
        self.status_var.set(text)

    # --------------------------------------------------------- Connection

    def _refresh_ports(self):
        ports = self.client.list_ports()
        self.port_map = {port["device"]: port for port in ports}
        labels = [port["device"] for port in ports]
        self.connection_panel.set_port_values(labels)

        if not ports:
            self.port_var.set("")
            self.port_status_var.set("No serial ports found")
            return

        if self.port_var.get() not in self.port_map:
            preferred = next((port["device"] for port in ports if looks_like_pico(port)), labels[0])
            self.port_var.set(preferred)

        self.port_status_var.set(f"{len(ports)} serial port(s) available")

        if self.auto_connect_var.get() and not self.auto_connected and not self.client.is_connected() and len(labels) == 1:
            self.auto_connected = True
            self.root.after(250, self.connect)

    def _auto_refresh_ports(self):
        if self.auto_refresh_var.get() and not self.client.is_connected():
            self._refresh_ports()
        self.root.after(PORT_REFRESH_MS, self._auto_refresh_ports)

    def _set_connected_state(self, connected):
        self.connection_panel.set_connected_state(connected)
        for panel in self.panels:
            panel.set_enabled(connected)

    def connect(self):
        port = self.port_var.get().strip()
        if not port:
            messagebox.showerror("Connect Error", "Select a serial port")
            return
        try:
            baud = int(self.baud_var.get().strip())
        except ValueError:
            messagebox.showerror("Connect Error", "Baud must be a whole number")
            return
        try:
            self.log_event("TX", f"connect {port} {baud}")
            self.client.connect(port=port, baudrate=baud)
            self._set_connected_state(True)
            self.set_status(f"Connected to {port} @ {baud}; waiting for Pico bridge")
            self.append_log(f"> connected {port} {baud}")
            # Opening a Pico USB serial port can reset MicroPython; give the
            # bridge time to print READY before the first commands land.
            self.root.after(PICO_BOOT_WAIT_MS, self._initial_bridge_check)
        except Exception as exc:
            self.set_status("Connection failed")
            self.log_event("ERR", f"connect failed: {exc}")
            messagebox.showerror("Connect Error", str(exc))

    def _initial_bridge_check(self):
        if not self.client.is_connected():
            return
        self.send("PING")
        self.send("STATUS")
        self.send("CAL STATUS")

    def disconnect(self):
        self.client.disconnect()
        self._set_connected_state(False)
        self.set_status("Disconnected")
        self.append_log("> disconnected")
        self.log_event("APP", "Disconnected")
        self.session.footer()

    # ------------------------------------------------------------- Comms

    def send(self, cmd, log=True):
        try:
            self.last_tx_line = cmd
            self.client.send_line(cmd)
            if log:
                self.append_log(f"> {cmd}")
                self.log_event("TX", cmd)
            elif cmd.strip().upper() == "STATUS":
                self._silent_status_pending += 1
        except Exception as exc:
            self.log_event("ERR", f"send failed ({cmd}): {exc}")
            messagebox.showerror("Send Error", str(exc))

    def send_expect(self, cmd, on_result, match=None, timeout_ms=120000):
        """Send a command and call on_result(ok: bool, line: str) with its reply.

        `match` (default: the command text) is the substring an OK reply must
        contain to be treated as this command's answer, so unrelated acks
        (e.g. an ENABLE ack while awaiting a move) are not mistaken for it. Any
        ERR line is always taken as this command's failure. If nothing arrives
        within timeout_ms, on_result(False, "TIMEOUT ...") fires exactly once.
        """
        if not self.client.is_connected():
            on_result(False, "NOT CONNECTED: connect to the Pico first")
            return
        waiter = {
            "on_result": on_result,
            "done": False,
            "match": (match if match is not None else cmd).strip().upper(),
        }
        self._response_waiters.append(waiter)

        def _timeout():
            if waiter["done"]:
                return
            waiter["done"] = True
            try:
                self._response_waiters.remove(waiter)
            except ValueError:
                pass
            on_result(False, f"TIMEOUT: no reply to '{cmd}' within {timeout_ms // 1000}s")

        self.root.after(timeout_ms, _timeout)
        self.send(cmd)

    def _dispatch_response(self, line):
        # Discard any already-resolved waiters at the head of the queue.
        while self._response_waiters and self._response_waiters[0]["done"]:
            self._response_waiters.pop(0)
        if not self._response_waiters:
            return
        waiter = self._response_waiters[0]
        up = line.upper()
        is_err = up.startswith("ERR")
        match = waiter["match"]
        if not (is_err or match in up):
            # An OK ack for some other command; leave this waiter pending.
            return
        waiter["done"] = True
        self._response_waiters.pop(0)
        try:
            waiter["on_result"](not is_err, line)
        except Exception as exc:
            self.log_event("ERR", f"response handler failed: {exc}")

    def _heartbeat(self):
        if self.client.is_connected():
            # Silent: this fires every second purely to keep the live status
            # panels fresh. Logging it verbatim each time would flood the
            # console/session log with a near-identical line every second -
            # an explicit Status click (Diagnostics tab) still logs normally.
            self.send("STATUS", log=False)
        self.root.after(HEARTBEAT_MS, self._heartbeat)

    def _poll_rx_queue(self):
        try:
            while True:
                self._handle_line(self.client.rx_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(120, self._poll_rx_queue)

    def _handle_line(self, line):
        self.last_rx_line = line
        is_silent_status = line.upper().startswith("OK STATUS") and self._silent_status_pending > 0
        if is_silent_status:
            self._silent_status_pending -= 1
        else:
            self.append_log(line)
            self.log_event("RX", line)

        if line.upper().startswith("OK STATUS"):
            self._apply_status_fields(_parse_status_fields(line))
            return
        # Route command replies (OK <not STATUS> / ERR) to any pending
        # send_expect() waiter before the generic status handling below.
        if line.startswith("OK") or line.startswith("ERR"):
            self._dispatch_response(line)
        if line.startswith("ERR"):
            self.set_status(line)
            return
        if line.startswith("OK PONG"):
            self.set_status("Pico reachable")
            return

    def _apply_status_fields(self, fields):
        self.status_fields = fields

        def get(key, default="?"):
            return fields.get(key, default)

        self.sm1_pos_var.set(get("sm1_pos"))
        sm1_main = get("sm1_main")
        self.sm1_main_var.set(sm1_main if sm1_main not in ("0", "None", None, "?") else "not set")
        self.home_switch_var.set("TRIGGERED" if get("home_switch") == "1" else "open")
        self.pause_btn_var.set("PRESSED" if get("pause_btn") == "1" else "released")
        self.sm2_pos_var.set(get("sm2_pos"))
        self.sm2_closed_var.set(get("sm2_closed") if get("sm2_closed") not in ("None", None) else "not calibrated")
        self.gripper_state_var.set(get("gripper", "UNKNOWN"))
        self.demo_phase_var.set(get("demo_phase") if get("demo_phase") not in ("None", None) else "(not started)")
        self.demo_running_var.set("running" if get("demo_running") == "1" else "stopped")
        needs_attention = get("needs_attention") == "1"
        was_attention = self.needs_attention_var.get()
        self.needs_attention_var.set(needs_attention)
        if needs_attention and not was_attention:
            messagebox.showwarning(
                "Demo paused - needs attention",
                "The demo hit a fault and auto-paused (for example homing could "
                "not find the limit switch).\n"
                "Check the Pico Console for the error, then click Resume in the "
                "Demo Cycle tab.",
            )
        self.cycle_count_var.set(get("cycle_count"))
        self.sm2_ready_var.set("ready" if get("sm2_ready") == "1" else "NOT WIRED / CHECK UART")
        self.sm1_enabled_var.set("ENABLED" if get("sm1_enabled") == "1" else "DISABLED")
        self.sm2_enabled_var.set("ENABLED" if get("sm2_enabled") == "1" else "DISABLED")
        self.sm1_speed_us_var.set(get("sm1_speed_us", "AUTO"))
        self.sm2_speed_us_var.set(get("sm2_speed_us", "AUTO"))

    # ------------------------------------------------------------- Report

    def save_report(self):
        try:
            self.session.snapshot(
                "Current State",
                {
                    "Port": self.port_var.get() or "(none)",
                    "Baud": self.baud_var.get(),
                    "Connected": self.client.is_connected(),
                    "SM1 position (steps)": self.sm1_pos_var.get(),
                    "SM1 MAIN (steps)": self.sm1_main_var.get(),
                    "Home switch": self.home_switch_var.get(),
                    "SM1 enabled": self.sm1_enabled_var.get(),
                    "SM2 position (steps)": self.sm2_pos_var.get(),
                    "SM2 closed (steps)": self.sm2_closed_var.get(),
                    "SM2 enabled": self.sm2_enabled_var.get(),
                    "Gripper state": self.gripper_state_var.get(),
                    "Demo phase": self.demo_phase_var.get(),
                    "Demo running": self.demo_running_var.get(),
                    "Needs attention": self.needs_attention_var.get(),
                    "Cycle count": self.cycle_count_var.get(),
                    "Last TX": self.last_tx_line or "(none)",
                    "Last RX": self.last_rx_line or "(none)",
                },
            )
            self.set_status(f"Report saved to {self.session.path}")
            self.append_log(f"> report saved: {self.session.path}")
        except Exception as exc:
            self.log_event("ERR", f"report save failed: {exc}")
            messagebox.showerror("Report Error", str(exc))


def main():
    root = ttk.Window(themename="superhero")
    app = MotorControlApp(root)

    def on_close():
        try:
            if app.client.is_connected():
                app.send("ESTOP")
                time.sleep(0.05)
            app.disconnect()
        finally:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

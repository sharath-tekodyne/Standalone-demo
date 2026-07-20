"""Main window: connection bar + tabbed panels + always-visible console.

Grows one panel per rebuild step. This file owns:
- the serial link and the RX pump (drained on the Tk thread),
- a live STATUS mirror (parsed from the ~1 Hz heartbeat) exposed as StringVars
  the panels bind to,
- send_expect(): send a command and get its exact OK/ERR reply (or a timeout)
  on the Tk thread, so buttons can report success/failure per action.

Everything is button-driven; the console is for visibility/debugging only.
"""

import queue
import tkinter as tk
from tkinter import ttk

from gui.serial_link import DEFAULT_BAUD, IMPORT_ERROR, SerialLink
from gui.panels.jog_panel import JogPanel
from gui.panels.home_panel import HomePanel
from gui.panels.main_panel import MainPanel
from gui.panels.gripper_panel import GripperPanel
from gui.panels.cycle_panel import CyclePanel
from gui.panels.sequence_panel import SequencePanel
from gui.panels.four_jaw_panel import FourJawPanel

RX_POLL_MS = 60
HEARTBEAT_MS = 1000
MAX_LINES_PER_POLL = 300   # cap work per RX tick so a flood can't freeze the UI
MAX_CONSOLE_LINES = 800    # trim the console so it can't grow without bound


def parse_status(line):
    """'OK STATUS k=v k=v ...' -> {k: v}. Returns {} for anything else."""
    up = line.upper()
    if not up.startswith("OK STATUS"):
        return {}
    body = line.split(" ", 2)[-1]
    fields = {}
    for token in body.split():
        if "=" in token:
            key, _, value = token.partition("=")
            fields[key] = value
    return fields


class App:
    def __init__(self, root):
        self.root = root
        self.link = SerialLink()
        self._ports = []
        self._waiters = []
        self._log_next_status = False

        root.title("Pico Jog/Gripper - Rebuild")
        root.geometry("1880x1120")   # single-screen layout for a 1920x1200 display
        root.minsize(1200, 800)

        # ---- live STATUS mirror (panels bind to these) --------------------
        self.sm1_pos_var = tk.StringVar(value="?")
        self.sm1_enabled_var = tk.StringVar(value="?")
        self.sm2_pos_var = tk.StringVar(value="?")
        self.sm2_enabled_var = tk.StringVar(value="?")
        self.sm2_ready_var = tk.StringVar(value="?")
        self.home_switch_var = tk.StringVar(value="?")
        self.sm1_main_var = tk.StringVar(value="?")
        self.gripper_state_var = tk.StringVar(value="?")
        self.sm2_closed_var = tk.StringVar(value="?")
        self.sm2_sgthrs_var = tk.StringVar(value="?")
        self.sm2_speed_var = tk.StringVar(value="?")
        self.sm2_torque_var = tk.StringVar(value="?")
        self.demo_phase_var = tk.StringVar(value="?")
        self.demo_running_var = tk.StringVar(value="?")
        self.cycle_count_var = tk.StringVar(value="?")
        self.needs_attention_var = tk.StringVar(value="")

        self._build()
        self._refresh_ports()
        if IMPORT_ERROR:
            self.log(f"! pyserial not available: {IMPORT_ERROR}")
        self.root.after(RX_POLL_MS, self._poll_rx)
        self.root.after(HEARTBEAT_MS, self._heartbeat)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------- build

    def _build(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(bar, text="Port:").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(bar, textvariable=self.port_var, width=32, state="readonly")
        self.port_combo.pack(side="left", padx=4)
        ttk.Button(bar, text="Refresh", command=self._refresh_ports).pack(side="left", padx=2)
        self.connect_btn = ttk.Button(bar, text="Connect", command=self._toggle_connect)
        self.connect_btn.pack(side="left", padx=6)
        self.status_var = tk.StringVar(value="disconnected")
        ttk.Label(bar, textvariable=self.status_var, font=("Segoe UI", 9, "bold")).pack(side="left", padx=8)

        # One section per tab; the large window keeps each section fully in view.
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=4)
        self.jog_panel = JogPanel(self.notebook, self)
        self.notebook.add(self.jog_panel, text="Jog / Enable")
        self.home_panel = HomePanel(self.notebook, self)
        self.notebook.add(self.home_panel, text="Homing")
        self.main_panel = MainPanel(self.notebook, self)
        self.notebook.add(self.main_panel, text="MAIN / Move")
        self.gripper_panel = GripperPanel(self.notebook, self)
        self.notebook.add(self.gripper_panel, text="Gripper")
        self.cycle_panel = CyclePanel(self.notebook, self)
        self.notebook.add(self.cycle_panel, text="Cycle")
        self.sequence_panel = SequencePanel(self.notebook, self)
        self.notebook.add(self.sequence_panel, text="Sequence")
        self.four_jaw_panel = FourJawPanel(self.notebook, self)
        self.notebook.add(self.four_jaw_panel, text="4-Jaw Demo")

        quick = ttk.Frame(self.root)
        quick.pack(fill="x", padx=8)
        ttk.Label(quick, text="Diagnostics:").pack(side="left")
        ttk.Button(quick, text="PING", command=lambda: self.send("PING")).pack(side="left", padx=2, pady=4)
        ttk.Button(quick, text="STATUS", command=self._request_status).pack(side="left", padx=2)
        ttk.Button(quick, text="DEBUG ON", command=lambda: self.send("DEBUG ON")).pack(side="left", padx=2)
        ttk.Button(quick, text="DEBUG OFF", command=lambda: self.send("DEBUG OFF")).pack(side="left", padx=2)
        ttk.Button(quick, text="Clear log", command=self._clear_log).pack(side="left", padx=8)

        console_frame = ttk.LabelFrame(self.root, text="Console (TX / RX)")
        console_frame.pack(fill="both", expand=False, padx=8, pady=(4, 8))
        self.console = tk.Text(console_frame, height=12, wrap="word", state="disabled")
        yscroll = ttk.Scrollbar(console_frame, orient="vertical", command=self.console.yview)
        self.console.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)

    # -------------------------------------------------------- connection

    def _refresh_ports(self):
        self._ports = SerialLink.list_ports()
        self.port_combo["values"] = [f"{dev}   {desc}".strip() for dev, desc in self._ports]
        if self._ports and self.port_combo.current() < 0:
            self.port_combo.current(0)

    def _selected_port(self):
        idx = self.port_combo.current()
        if 0 <= idx < len(self._ports):
            return self._ports[idx][0]
        return None

    def _toggle_connect(self):
        if self.link.is_open():
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        port = self._selected_port()
        if not port:
            self.log("! no port selected (click Refresh, then pick one)")
            return
        try:
            self.link.open(port, DEFAULT_BAUD)
        except Exception as exc:
            self.log(f"! connect failed: {exc}")
            return
        self.status_var.set(f"connected  {port}  @{DEFAULT_BAUD}")
        self.connect_btn.configure(text="Disconnect")
        self.log(f"* connected to {port}")
        # Quiet the firmware's per-command DBG stream (it boots DEBUG ON); this
        # cuts serial chatter that was flooding the console/UI. Use the DEBUG ON
        # button if you want the verbose bridge logging back.
        self.send("DEBUG OFF", log=False)

    def _disconnect(self):
        self.link.close()
        self.status_var.set("disconnected")
        self.connect_btn.configure(text="Connect")
        for var in (self.sm1_pos_var, self.sm1_enabled_var, self.sm2_pos_var,
                    self.sm2_enabled_var, self.sm2_ready_var, self.home_switch_var,
                    self.sm1_main_var, self.gripper_state_var, self.sm2_closed_var,
                    self.sm2_sgthrs_var, self.sm2_speed_var, self.sm2_torque_var,
                    self.demo_phase_var, self.demo_running_var, self.cycle_count_var):
            var.set("?")
        self.needs_attention_var.set("")
        self.log("* disconnected")

    def _on_close(self):
        # De-energize both drivers on exit (§1.8) so nothing is left holding
        # current / cooking after the window closes.
        try:
            if self.link.is_open():
                self.link.send("ESTOP")
        except Exception:
            pass
        try:
            self.link.close()
        finally:
            self.root.destroy()

    # -------------------------------------------------------------- comms

    def send(self, line, log=True):
        if not self.link.is_open():
            if log:
                self.log("! not connected")
            return
        try:
            self.link.send(line)
            if log:
                self.log(f"> {line}")
        except Exception as exc:
            self.log(f"! send failed: {exc}")

    def send_expect(self, cmd, on_result, match=None, timeout_ms=15000):
        """Send cmd; call on_result(ok: bool, line: str) with its OK/ERR reply.

        An OK reply must contain `match` to count as this command's answer, so
        unrelated acks aren't mistaken for it; any ERR is taken as this
        command's failure. The default match is the command's first two tokens
        (axis + subcommand, e.g. 'SM1 JOG'), because this firmware echoes that
        much but not the arguments (reply is 'OK SM1 JOG completed=.. position=..').
        Fires exactly once (reply or timeout).
        """
        if not self.link.is_open():
            on_result(False, "not connected")
            return
        default_match = " ".join(cmd.strip().split()[:2])
        waiter = {"done": False,
                  "match": (match if match is not None else default_match).strip().upper(),
                  "on_result": on_result}
        self._waiters.append(waiter)

        def _timeout():
            if waiter["done"]:
                return
            waiter["done"] = True
            try:
                self._waiters.remove(waiter)
            except ValueError:
                pass
            on_result(False, f"timeout: no reply to '{cmd}'")

        self.root.after(timeout_ms, _timeout)
        self.send(cmd)

    def _dispatch(self, line):
        while self._waiters and self._waiters[0]["done"]:
            self._waiters.pop(0)
        if not self._waiters:
            return
        waiter = self._waiters[0]
        up = line.upper()
        is_err = up.startswith("ERR")
        if not (is_err or waiter["match"] in up):
            return  # an ack for some other command; keep waiting
        waiter["done"] = True
        self._waiters.pop(0)
        try:
            waiter["on_result"](not is_err, line)
        except Exception as exc:
            self.log(f"! result handler error: {exc}")

    def _request_status(self):
        self._log_next_status = True
        self.send("STATUS")

    def _heartbeat(self):
        if self.link.is_open():
            self.send("STATUS", log=False)
        self.root.after(HEARTBEAT_MS, self._heartbeat)

    def _poll_rx(self):
        # Process at most MAX_LINES_PER_POLL per tick, then return control to Tk.
        # A bounded loop means even a continuous flood of lines from the Pico
        # can never lock the UI thread (the old 'while True' drain could).
        processed = 0
        try:
            while processed < MAX_LINES_PER_POLL:
                kind, payload = self.link.rx_queue.get_nowait()
                processed += 1
                if kind == "line":
                    try:
                        self._handle_line(payload)
                    except Exception as exc:
                        # A garbled/partial line (common when the Pico resets)
                        # must never crash the UI - log and keep going.
                        self.log(f"! bad line {payload!r}: {exc}")
                elif kind == "error":
                    self.log(f"! serial error: {payload}")
                    self._disconnect()
        except queue.Empty:
            pass
        self.root.after(RX_POLL_MS, self._poll_rx)

    def _handle_line(self, line):
        fields = parse_status(line)
        if fields:
            self._apply_status(fields)
            if self._log_next_status:
                self._log_next_status = False
                self.log(line)
            return  # heartbeat noise otherwise stays out of the console
        self.log(line)
        if line.startswith("OK") or line.startswith("ERR"):
            self._dispatch(line)

    def _apply_status(self, f):
        self.sm1_pos_var.set(f.get("sm1_pos", "?"))
        self.sm2_pos_var.set(f.get("sm2_pos", "?"))
        self.sm1_enabled_var.set("ENABLED" if f.get("sm1_enabled") == "1" else "DISABLED")
        self.sm2_enabled_var.set("ENABLED" if f.get("sm2_enabled") == "1" else "DISABLED")
        self.sm2_ready_var.set("ready" if f.get("sm2_ready") == "1" else "NOT READY")
        if "home_switch" in f:
            self.home_switch_var.set("TRIGGERED" if f.get("home_switch") == "1" else "open")
        if "sm1_main" in f:
            v = f.get("sm1_main")
            self.sm1_main_var.set(v if v not in ("None", "0") else "not set")
        if "gripper" in f:
            self.gripper_state_var.set(f.get("gripper"))
        if "sm2_closed" in f:
            c = f.get("sm2_closed")
            self.sm2_closed_var.set(c if c not in ("None",) else "not set")
        if "sm2_sgthrs" in f:
            self.sm2_sgthrs_var.set(f.get("sm2_sgthrs"))
        if "sm2_speed" in f:
            self.sm2_speed_var.set(f.get("sm2_speed"))
        if "sm2_torque" in f:
            self.sm2_torque_var.set(f.get("sm2_torque"))
        if "demo_phase" in f:
            p = f.get("demo_phase")
            self.demo_phase_var.set(p if p not in ("None",) else "(idle)")
        if "demo_running" in f:
            self.demo_running_var.set("RUNNING" if f.get("demo_running") == "1" else "stopped")
        if "cycle_count" in f:
            self.cycle_count_var.set(f.get("cycle_count"))
        if "needs_attention" in f:
            self.needs_attention_var.set(
                "NEEDS ATTENTION - check console, fix, then Resume" if f.get("needs_attention") == "1" else "")

    # ------------------------------------------------------------ console

    def log(self, text):
        self.console.configure(state="normal")
        self.console.insert("end", text + "\n")
        # keep only the last MAX_CONSOLE_LINES so the widget can't grow forever
        line_count = int(self.console.index("end-1c").split(".")[0])
        if line_count > MAX_CONSOLE_LINES:
            self.console.delete("1.0", "{}.0".format(line_count - MAX_CONSOLE_LINES))
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

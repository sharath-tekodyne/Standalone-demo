"""Cycle tab (Step 6): run the full 8-phase demo loop.

Start homes to the switch, then loops:
  OPEN@HOME -> HOME->MAIN -> MAIN->HOME -> CLOSE@HOME ->
  HOME->MAIN -> MAIN->HOME -> OPEN@HOME -> CLOSE@HOME -> (repeat)

Pause freezes in place (exact phase + position kept); Resume continues that
exact phase; Reset clears progress back to idle. All the individual moves were
proven in the Homing / MAIN / Gripper tabs, so this just sequences them.
Requires MAIN calibrated and the gripper OPEN/CLOSED marked first.
"""

import tkinter as tk
from tkinter import ttk

CYCLE_TIMEOUT_MS = 20000   # START/PAUSE/RESUME just ack quickly; the loop runs on the Pico


class CyclePanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.status = tk.StringVar(value="Calibrate MAIN + gripper first, then Start. Start homes, then loops.")
        self._build()
        self.app.needs_attention_var.trace_add("write", lambda *_: self._paint_attention())

    def _build(self):
        ctl = ttk.LabelFrame(self, text="Cycle control")
        ctl.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Button(ctl, text="Start", command=lambda: self._cmd("DEMO START")).pack(side="left", padx=6, pady=8)
        ttk.Button(ctl, text="Pause", command=lambda: self._cmd("DEMO PAUSE")).pack(side="left", padx=6, pady=8)
        ttk.Button(ctl, text="Resume", command=lambda: self._cmd("DEMO RESUME")).pack(side="left", padx=6, pady=8)
        ttk.Button(ctl, text="Reset", command=lambda: self._cmd("DEMO RESET")).pack(side="left", padx=6, pady=8)
        ttk.Button(ctl, text="ESTOP", command=self._estop).pack(side="left", padx=16, pady=8)
        ttk.Button(ctl, text="Custom sequence ▶", command=self._open_sequence).pack(side="right", padx=8, pady=8)

        live = ttk.LabelFrame(self, text="Live cycle status")
        live.pack(fill="x", padx=10, pady=6)
        self._kv(live, "Running:", self.app.demo_running_var)
        self._kv(live, "Phase:", self.app.demo_phase_var)
        self._kv(live, "Cycle count:", self.app.cycle_count_var)
        self._kv(live, "SM1 position (steps):", self.app.sm1_pos_var)
        self._kv(live, "Gripper:", self.app.gripper_state_var)
        self._kv(live, "Home switch:", self.app.home_switch_var)

        self.attention = tk.Label(self, textvariable=self.app.needs_attention_var,
                                  font=("Segoe UI", 11, "bold"), fg="white", bg="#b00020")
        # only shown when there is an attention message (see _paint_attention)
        ttk.Label(self, textvariable=self.status, wraplength=580, justify="left",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(6, 8))
        self._paint_attention()

    def _kv(self, parent, label, var):
        r = ttk.Frame(parent); r.pack(anchor="w", padx=8, pady=2)
        ttk.Label(r, text=label).pack(side="left")
        ttk.Label(r, textvariable=var, font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)

    def _paint_attention(self):
        if self.app.needs_attention_var.get():
            self.attention.pack(fill="x", padx=10, pady=(0, 6))
        else:
            self.attention.pack_forget()

    def _cmd(self, command):
        if not self.app.link.is_open():
            self.status.set("Not connected.")
            return
        self.status.set("{} ...".format(command))
        self.app.send_expect(command, self._report, timeout_ms=CYCLE_TIMEOUT_MS)

    def _report(self, ok, line):
        self.status.set(line if ok else "ERROR: " + line)

    def _estop(self):
        self.app.send("ESTOP")
        self.status.set("ESTOP - motors disabled, cycle paused.")

    def _open_sequence(self):
        # jump to the Sequence Builder tab to run a custom sequence
        self.app.notebook.select(self.app.sequence_panel)

"""Step 1 panel: Enable/Disable + Jog CW/ACW for SM1 and SM2, all buttons.

Live 'Enabled' and 'Position' come from the app's STATUS mirror (updated by
the ~1 Hz heartbeat). Each button uses app.send_expect() so the exact OK/ERR
(or a timeout) is reported in the console per action - e.g. jogging while an
axis is disabled surfaces the firmware's clear error instead of silently
doing nothing.
"""

import tkinter as tk
from tkinter import ttk

STEP_SIZES = ["10", "50", "100", "200", "500", "1000", "1600"]


class JogPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._step_vars = {}
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self._axis_box(0, "SM1", self.app.sm1_enabled_var, self.app.sm1_pos_var)
        self._axis_box(1, "SM2", self.app.sm2_enabled_var, self.app.sm2_pos_var)

    def _axis_box(self, col, axis, enabled_var, pos_var):
        box = ttk.LabelFrame(self, text=axis)
        box.grid(row=0, column=col, padx=8, pady=8, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.columnconfigure(1, weight=1)

        ttk.Button(box, text="Enable", command=lambda: self._cmd(f"{axis} ENABLE")).grid(
            row=0, column=0, padx=4, pady=4, sticky="ew")
        ttk.Button(box, text="Disable", command=lambda: self._cmd(f"{axis} DISABLE")).grid(
            row=0, column=1, padx=4, pady=4, sticky="ew")

        ttk.Label(box, text="Enabled:").grid(row=1, column=0, padx=4, pady=2, sticky="w")
        ttk.Label(box, textvariable=enabled_var, font=("Segoe UI", 9, "bold")).grid(
            row=1, column=1, padx=4, pady=2, sticky="w")
        ttk.Label(box, text="Position (steps):").grid(row=2, column=0, padx=4, pady=2, sticky="w")
        ttk.Label(box, textvariable=pos_var, font=("Segoe UI", 9, "bold")).grid(
            row=2, column=1, padx=4, pady=2, sticky="w")

        ttk.Label(box, text="Step size:").grid(row=3, column=0, padx=4, pady=(10, 2), sticky="w")
        step_var = tk.StringVar(value="200")
        self._step_vars[axis] = step_var
        ttk.Combobox(box, textvariable=step_var, values=STEP_SIZES, width=8).grid(
            row=3, column=1, padx=4, pady=(10, 2), sticky="w")

        ttk.Button(box, text="Jog ACW", command=lambda: self._jog(axis, "ACW")).grid(
            row=4, column=0, padx=4, pady=6, sticky="ew")
        ttk.Button(box, text="Jog CW", command=lambda: self._jog(axis, "CW")).grid(
            row=4, column=1, padx=4, pady=6, sticky="ew")

    def _cmd(self, command):
        self.app.send_expect(command, self._report)

    def _jog(self, axis, direction):
        raw = self._step_vars[axis].get().strip()
        try:
            steps = int(raw)
            if steps < 1:
                raise ValueError
        except ValueError:
            self.app.log(f"! step size '{raw}' must be a positive whole number")
            return
        self.app.send_expect(f"{axis} JOG {direction} {steps}", self._report)

    def _report(self, ok, line):
        # OK already shows in the console; only shout on failure.
        if not ok:
            self.app.log(f"! {line}")

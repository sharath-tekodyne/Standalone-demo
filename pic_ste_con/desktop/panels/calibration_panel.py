"""One-time calibration workflow.

SM1 HOME is found physically by the limit switch ("Home to switch" here, or
SM1 HOME). SM1 MAIN is a fixed step offset that you measure once with
firmware/calibrate_main_steps.py and paste into protocol.SM1_MAIN_STEPS - it
is shown here read-only so you can confirm it is set. SM2 OPEN/CLOSED are
still marked by hand: jog the jaws (Manual Control tab) to each limit and
click the matching "Mark" button. OPEN is always step 0 for SM2; marking it
re-zeroes the jaw axis.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as ttk


class CalibrationPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.widgets = []
        self.ready_var = tk.StringVar(value="Not calibrated")
        self._build()

    def _track(self, widget):
        self.widgets.append(widget)
        return widget

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        instructions = (
            "1. Enable SM1 (Manual Control tab), then click 'Home to switch' - SM1 drives CW\n"
            "   into the limit switch and zeroes there. That point is HOME.\n"
            "2. MAIN is a fixed step count: run firmware/calibrate_main_steps.py once, paste\n"
            "   the printed number into protocol.SM1_MAIN_STEPS, and re-upload protocol.py.\n"
            "   The value below should then read a non-zero 'MAIN (steps)'.\n"
            "3. Jog SM2 jaws fully open, then click 'Mark OPEN here'.\n"
            "4. Jog SM2 jaws fully closed (no object between them), then click 'Mark CLOSED here'.\n"
            "5. Click 'Refresh Calibration Status' - once MAIN and CLOSED are set, the demo can start."
        )
        ttk.Label(self, text=instructions, justify="left").grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="w")

        sm1 = ttk.LabelFrame(self, text="SM1 - Platform (HOME by limit switch, MAIN by step count)")
        sm1.grid(row=1, column=0, padx=8, pady=8, sticky="nsew")
        self._track(ttk.Button(sm1, text="Home to switch", command=lambda: self.app.send("SM1 HOME"))).grid(
            row=0, column=0, padx=6, pady=6
        )
        ttk.Label(sm1, text="Home switch:").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(sm1, textvariable=self.app.home_switch_var).grid(row=1, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(sm1, text="Position (steps):").grid(row=2, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(sm1, textvariable=self.app.sm1_pos_var).grid(row=2, column=1, padx=6, pady=6, sticky="w")
        ttk.Label(sm1, text="MAIN (steps):").grid(row=3, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(sm1, textvariable=self.app.sm1_main_var).grid(row=3, column=1, padx=6, pady=6, sticky="w")

        sm2 = ttk.LabelFrame(self, text="SM2 - Gripper jaw positions")
        sm2.grid(row=1, column=1, padx=8, pady=8, sticky="nsew")
        self._track(ttk.Button(sm2, text="Mark OPEN here", command=lambda: self.app.send("SM2 MARK OPEN"))).grid(
            row=0, column=0, padx=6, pady=6
        )
        self._track(ttk.Button(sm2, text="Mark CLOSED here", command=lambda: self.app.send("SM2 MARK CLOSED"))).grid(
            row=0, column=1, padx=6, pady=6
        )
        ttk.Label(sm2, text="Closed (steps):").grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(sm2, textvariable=self.app.sm2_closed_var).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, columnspan=2, padx=8, pady=10, sticky="ew")
        self._track(ttk.Button(actions, text="Refresh Calibration Status", command=lambda: self.app.send("CAL STATUS"))).grid(
            row=0, column=0, padx=6, pady=6
        )
        self._track(ttk.Button(actions, text="Clear SM2 Calibration", command=self._confirm_clear)).grid(
            row=0, column=1, padx=6, pady=6
        )
        ttk.Label(actions, textvariable=self.ready_var, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=2, padx=12, pady=6, sticky="w"
        )

    def _confirm_clear(self):
        if messagebox.askyesno(
            "Clear calibration",
            "This clears the SM2 CLOSED mark (OPEN stays at step 0). SM1 MAIN is a "
            "fixed constant in protocol.py and HOME is found by the limit switch, so "
            "neither is affected. Continue?",
        ):
            self.app.send("CAL CLEAR")

    def set_enabled(self, enabled):
        state = ["!disabled"] if enabled else ["disabled"]
        for widget in self.widgets:
            widget.state(state)

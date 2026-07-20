"""Homing tab.

Step 2: a big live limit-switch indicator.
Step 3: a 'Find HOME' seek - drive SM1 CW until the switch activates; that
point is defined as HOME (position 0). Interruptible with ESTOP.

Everything is button-driven. 'Find HOME' auto-enables SM1 first (enabling only
energizes the coils, no motion), then sends SM1 HOME and reports the result.
"""

import tkinter as tk
from tkinter import ttk

HOME_TIMEOUT_MS = 180000   # homing can be a long seek; give it plenty of time


class HomePanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.seek_status = tk.StringVar(value="Idle - click 'Find HOME' to seek the switch.")
        self._build()
        self.app.home_switch_var.trace_add("write", lambda *_: self._recolor())
        self._recolor()

    def _build(self):
        # --- live switch indicator (Step 2) -------------------------------
        sw = ttk.LabelFrame(self, text="SM1 home limit switch (live)")
        sw.pack(fill="x", padx=10, pady=(10, 6))
        self.indicator = tk.Label(
            sw, textvariable=self.app.home_switch_var,
            font=("Segoe UI", 22, "bold"), width=14,
            relief="ridge", bd=3, padx=10, pady=10,
        )
        self.indicator.pack(padx=10, pady=8)
        self.hint = ttk.Label(sw, text="", justify="center")
        self.hint.pack(pady=(0, 8))

        # --- establish HOME (Step 3) --------------------------------------
        hm = ttk.LabelFrame(self, text="Establish HOME (drive CW until the switch)")
        hm.pack(fill="x", padx=10, pady=6)
        hm.columnconfigure(0, weight=1)
        hm.columnconfigure(1, weight=1)

        ttk.Label(
            hm, justify="left", wraplength=560,
            text=("There is no HOME until this runs. 'Find HOME' drives SM1 CW until the\n"
                  "switch activates and sets that point as HOME (position 0). It stops by\n"
                  "itself at the switch; use ESTOP to abort. If the switch is never found\n"
                  "it stops safely after a step cap and reports an error."),
        ).grid(row=0, column=0, columnspan=2, padx=8, pady=(6, 8), sticky="w")

        self.find_btn = ttk.Button(hm, text="Find HOME", command=self._find_home)
        self.find_btn.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        ttk.Button(hm, text="ESTOP (abort)", command=self._estop).grid(
            row=1, column=1, padx=8, pady=4, sticky="ew")

        row = ttk.Frame(hm)
        row.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 2))
        ttk.Label(row, text="SM1 position (steps):").pack(side="left")
        ttk.Label(row, textvariable=self.app.sm1_pos_var, font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)

        ttk.Label(hm, textvariable=self.seek_status, wraplength=560, justify="left",
                  font=("Segoe UI", 9, "bold")).grid(row=3, column=0, columnspan=2, padx=8, pady=(4, 8), sticky="w")

    # ------------------------------------------------------------- actions

    def _find_home(self):
        if not self.app.link.is_open():
            self.seek_status.set("Not connected.")
            return
        # Auto-enable SM1 first (energize only, no motion), then seek. The
        # ENABLE ack won't match the 'SM1 HOME' reply, so it isn't mistaken for
        # the seek result.
        self.app.send("SM1 ENABLE")
        self.app.sm1_enabled_var.set("ENABLED")
        self.seek_status.set("Seeking the switch (driving CW)...")
        self.find_btn.state(["disabled"])
        self.app.send_expect("SM1 HOME", self._home_done, timeout_ms=HOME_TIMEOUT_MS)

    def _home_done(self, ok, line):
        self.find_btn.state(["!disabled"])
        if ok:
            # reply: OK SM1 HOME homed=1 position=0
            homed = "homed=1" in line
            if homed:
                self.seek_status.set("HOME established - position is now 0. " + line)
            else:
                self.seek_status.set("Seek was interrupted before the switch (aborted). " + line)
        else:
            self.seek_status.set("HOME FAILED: " + line +
                                 "  (check the switch is on the CW side and wired to GP21/GND)")

    def _estop(self):
        self.app.send("ESTOP")
        self.seek_status.set("ESTOP sent - motors disabled, any seek aborted.")

    # -------------------------------------------------------- switch color

    def _recolor(self):
        value = self.app.home_switch_var.get()
        if value == "TRIGGERED":
            self.indicator.configure(bg="#1e7d32", fg="white")
            self.hint.configure(text="Contact closed - switch reads pressed.")
        elif value == "open":
            self.indicator.configure(bg="#3a3a3a", fg="white")
            self.hint.configure(text="Contact open - switch not pressed (idle).")
        else:
            self.indicator.configure(bg="#8a6d00", fg="white")
            self.hint.configure(text="No reading yet - connect to the Pico.")

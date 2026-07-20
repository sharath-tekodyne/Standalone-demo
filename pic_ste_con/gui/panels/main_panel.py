"""MAIN / Move tab (Step 4).

- Go HOME / Go MAIN: absolute moves (chunked in firmware, interruptible by ESTOP).
- Calibrate MAIN: after Find HOME (Homing tab), either jog SM1 out to the MAIN
  position and 'Set MAIN = current position' (SM1 MARK MAIN), or type a known
  step count directly (SM1 SET MAINSTEPS). Both persist on the Pico.

All button-driven. Moves/jogs auto-enable SM1 first (energize only, no motion).
"""

import tkinter as tk
from tkinter import ttk

STEP_SIZES = ["10", "50", "100", "200", "500", "1000"]
MOVE_TIMEOUT_MS = 120000


class MainPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.jog_size = tk.StringVar(value="200")
        self.main_entry = tk.StringVar(value="")
        self.status = tk.StringVar(value="Find HOME first (Homing tab), then move or calibrate MAIN.")
        self._build()

    def _build(self):
        live = ttk.LabelFrame(self, text="Position")
        live.pack(fill="x", padx=10, pady=(10, 6))
        r1 = ttk.Frame(live); r1.pack(anchor="w", padx=8, pady=4)
        ttk.Label(r1, text="SM1 position (steps):").pack(side="left")
        ttk.Label(r1, textvariable=self.app.sm1_pos_var, font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)
        r2 = ttk.Frame(live); r2.pack(anchor="w", padx=8, pady=4)
        ttk.Label(r2, text="Current MAIN (steps):").pack(side="left")
        ttk.Label(r2, textvariable=self.app.sm1_main_var, font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)

        mv = ttk.LabelFrame(self, text="Move between HOME and MAIN")
        mv.pack(fill="x", padx=10, pady=6)
        for c in range(3):
            mv.columnconfigure(c, weight=1)
        ttk.Button(mv, text="Go HOME", command=lambda: self._goto("HOME")).grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        ttk.Button(mv, text="Go MAIN", command=lambda: self._goto("MAIN")).grid(row=0, column=1, padx=8, pady=8, sticky="ew")
        ttk.Button(mv, text="ESTOP", command=self._estop).grid(row=0, column=2, padx=8, pady=8, sticky="ew")

        cal = ttk.LabelFrame(self, text="Calibrate MAIN (steps from HOME)")
        cal.pack(fill="x", padx=10, pady=6)
        cal.columnconfigure(0, weight=1)
        cal.columnconfigure(1, weight=1)
        ttk.Label(
            cal, justify="left", wraplength=560,
            text=("After Find HOME: jog SM1 out to the MAIN position and click 'Set MAIN =\n"
                  "current position', or type a known step count below. Either way it's\n"
                  "saved on the Pico and used by Go MAIN and the demo."),
        ).grid(row=0, column=0, columnspan=2, padx=8, pady=(6, 8), sticky="w")

        ttk.Label(cal, text="Jog size:").grid(row=1, column=0, padx=8, sticky="w")
        ttk.Combobox(cal, textvariable=self.jog_size, values=STEP_SIZES, width=8).grid(row=1, column=1, padx=4, sticky="w")
        ttk.Button(cal, text="Jog ACW", command=lambda: self._jog("ACW")).grid(row=2, column=0, padx=8, pady=4, sticky="ew")
        ttk.Button(cal, text="Jog CW", command=lambda: self._jog("CW")).grid(row=2, column=1, padx=8, pady=4, sticky="ew")
        ttk.Button(cal, text="Set MAIN = current position", command=self._mark_main).grid(
            row=3, column=0, columnspan=2, padx=8, pady=(8, 4), sticky="ew")

        ttk.Separator(cal, orient="horizontal").grid(row=4, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(cal, text="Or set MAIN steps directly:").grid(row=5, column=0, columnspan=2, padx=8, sticky="w")
        ttk.Entry(cal, textvariable=self.main_entry, width=10).grid(row=6, column=0, padx=8, pady=4, sticky="w")
        ttk.Button(cal, text="Set MAIN steps", command=self._set_main_direct).grid(row=6, column=1, padx=4, pady=4, sticky="ew")

        ttk.Label(self, textvariable=self.status, wraplength=580, justify="left",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(4, 8))

    # ------------------------------------------------------------- helpers

    def _ready(self):
        if not self.app.link.is_open():
            self.status.set("Not connected.")
            return False
        return True

    def _auto_enable(self):
        self.app.send("SM1 ENABLE")
        self.app.sm1_enabled_var.set("ENABLED")

    def _report(self, ok, line):
        self.status.set(line if ok else "ERROR: " + line)

    def _on_main_set(self, ok, line):
        if ok:
            self.status.set("MAIN saved. " + line)
            self.app.send("STATUS", log=False)  # refresh the mirror promptly
        else:
            self.status.set("ERROR: " + line)

    # ------------------------------------------------------------- actions

    def _goto(self, name):
        if not self._ready():
            return
        self._auto_enable()
        self.status.set("Moving to {}...".format(name))
        self.app.send_expect("SM1 GOTO " + name, self._report, timeout_ms=MOVE_TIMEOUT_MS)

    def _jog(self, direction):
        if not self._ready():
            return
        raw = self.jog_size.get().strip()
        try:
            steps = int(raw)
            if steps < 1:
                raise ValueError
        except ValueError:
            self.status.set("Jog size must be a positive whole number.")
            return
        self._auto_enable()
        self.app.send_expect("SM1 JOG {} {}".format(direction, steps), self._report, timeout_ms=60000)

    def _mark_main(self):
        if not self._ready():
            return
        self.app.send_expect("SM1 MARK MAIN", self._on_main_set, match="SM1 MARK MAIN")

    def _set_main_direct(self):
        raw = self.main_entry.get().strip()
        try:
            steps = int(raw)
            if steps == 0:
                raise ValueError
        except ValueError:
            self.status.set("MAIN steps must be a nonzero whole number.")
            return
        if not self._ready():
            return
        self.app.send_expect("SM1 SET MAINSTEPS {}".format(steps), self._on_main_set)

    def _estop(self):
        self.app.send("ESTOP")
        self.status.set("ESTOP - motors disabled, move aborted.")

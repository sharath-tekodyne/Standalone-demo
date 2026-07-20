"""Gripper tab (Step 5) - fixed-position OPEN, force-feedback CLOSE.

OPEN returns the jaws to the calibrated OPEN reference (step 0), open-loop,
StallGuard OFF - it just goes to a fixed position.
CLOSE drives toward the calibrated CLOSED cap while watching StallGuard; it
stops early the instant it feels the object (a grip), or at the cap if nothing
is there (so it never over-closes). StallGuard sensitivity is tunable below.

Calibrate once: jog fully OPEN -> Mark OPEN (becomes 0); jog fully CLOSED with
nothing between the jaws -> Mark CLOSED (the safety cap). ACW opens, CW closes
by default - tell me if yours is reversed.
"""

import tkinter as tk
from tkinter import ttk

STEP_SIZES = ["10", "50", "100", "200", "500"]
GRIP_TIMEOUT_MS = 60000
TIGHT_FRAC = 0.85   # gripped and stopped past this fraction of the cap => "very tight"


class GripperPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.jog_size = tk.StringVar(value="100")
        self.sg_entry = tk.StringVar(value="")
        self.probe_steps = tk.StringVar(value="200")
        self.load_var = tk.StringVar(value="load: -   (Read to measure)")
        self.grip_var = tk.StringVar(value="-  (close to test grip)")
        self.status = tk.StringVar(value="Calibrate OPEN/CLOSED, then OPEN / CLOSE. Tune sensitivity if needed.")
        self._build()

    def _build(self):
        live = ttk.LabelFrame(self, text="SM2 gripper (live)")
        live.pack(fill="x", padx=10, pady=(10, 6))
        self._kv(live, "SM2 enabled:", self.app.sm2_enabled_var)
        self._kv(live, "UART/StallGuard:", self.app.sm2_ready_var)
        self._kv(live, "Jaw state:", self.app.gripper_state_var)
        self._kv(live, "SM2 position (steps):", self.app.sm2_pos_var)
        self._kv(live, "CLOSED cap (steps):", self.app.sm2_closed_var)
        self._kv(live, "StallGuard threshold:", self.app.sm2_sgthrs_var)

        en = ttk.Frame(self)
        en.pack(fill="x", padx=10, pady=4)
        ttk.Button(en, text="Enable SM2", command=self._enable).pack(side="left", padx=4)
        ttk.Button(en, text="Disable SM2", command=lambda: self._send("SM2 DISABLE")).pack(side="left", padx=4)
        ttk.Button(en, text="ESTOP", command=self._estop).pack(side="left", padx=12)

        oc = ttk.LabelFrame(self, text="Open (fixed position) / Close (until force)")
        oc.pack(fill="x", padx=10, pady=6)
        oc.columnconfigure(0, weight=1)
        oc.columnconfigure(1, weight=1)
        ttk.Button(oc, text="OPEN", command=self._open).grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        ttk.Button(oc, text="CLOSE (grip)", command=self._close).grid(row=0, column=1, padx=8, pady=8, sticky="ew")
        self.grip_label = tk.Label(oc, textvariable=self.grip_var, font=("Segoe UI", 15, "bold"),
                                   relief="ridge", bd=2, pady=8, bg="#3a3a3a", fg="white")
        self.grip_label.grid(row=1, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="ew")

        cal = ttk.LabelFrame(self, text="Calibrate OPEN / CLOSED")
        cal.pack(fill="x", padx=10, pady=6)
        cal.columnconfigure(0, weight=1)
        cal.columnconfigure(1, weight=1)
        ttk.Label(cal, text="Jog size:").grid(row=0, column=0, padx=8, pady=(6, 2), sticky="w")
        ttk.Combobox(cal, textvariable=self.jog_size, values=STEP_SIZES, width=8).grid(row=0, column=1, padx=4, pady=(6, 2), sticky="w")
        ttk.Button(cal, text="Jog ACW (open dir)", command=lambda: self._jog("ACW")).grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        ttk.Button(cal, text="Jog CW (close dir)", command=lambda: self._jog("CW")).grid(row=1, column=1, padx=8, pady=4, sticky="ew")
        ttk.Button(cal, text="Mark OPEN here", command=lambda: self._mark("OPEN")).grid(row=2, column=0, padx=8, pady=(6, 8), sticky="ew")
        ttk.Button(cal, text="Mark CLOSED here", command=lambda: self._mark("CLOSED")).grid(row=2, column=1, padx=8, pady=(6, 8), sticky="ew")

        sg = ttk.LabelFrame(self, text="StallGuard tuning (force feedback)")
        sg.pack(fill="x", padx=10, pady=6)
        ttk.Label(
            sg, justify="left", wraplength=560,
            text=("StallGuard only senses load in a speed/current band. If gripping barely\n"
                  "changes detection (no threshold works), raise SPEED and CURRENT first,\n"
                  "then set the threshold between the empty and gripped readings.\n"
                  "Threshold: higher = trips sooner (lighter force); lower = needs more force."),
        ).grid(row=0, column=0, columnspan=4, padx=8, pady=(6, 6), sticky="w")

        ttk.Label(sg, text="Close speed:").grid(row=1, column=0, padx=8, pady=2, sticky="w")
        ttk.Label(sg, textvariable=self.app.sm2_speed_var, width=8, font=("Segoe UI", 9, "bold")).grid(row=1, column=1, sticky="w")
        sbar = ttk.Frame(sg); sbar.grid(row=1, column=2, sticky="w")
        for lvl in ("LOW", "MEDIUM", "HIGH"):
            ttk.Button(sbar, text=lvl, width=8, command=lambda v=lvl: self._send_refresh("SM2 SET SPEED " + v)).pack(side="left", padx=2)

        ttk.Label(sg, text="Current:").grid(row=2, column=0, padx=8, pady=2, sticky="w")
        ttk.Label(sg, textvariable=self.app.sm2_torque_var, width=8, font=("Segoe UI", 9, "bold")).grid(row=2, column=1, sticky="w")
        cbar = ttk.Frame(sg); cbar.grid(row=2, column=2, sticky="w")
        for lvl in ("LOW", "MEDIUM", "HIGH"):
            ttk.Button(cbar, text=lvl, width=8, command=lambda v=lvl: self._send_refresh("SM2 SET TORQUE " + v)).pack(side="left", padx=2)

        row = ttk.Frame(sg); row.grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=(6, 8))
        ttk.Label(row, text="Set threshold (0-255):").pack(side="left")
        ttk.Entry(row, textvariable=self.sg_entry, width=6).pack(side="left", padx=6)
        ttk.Button(row, text="Apply", command=self._set_threshold).pack(side="left")

        load = ttk.LabelFrame(self, text="StallGuard load reading (probe)")
        load.pack(fill="x", padx=10, pady=6)
        r = ttk.Frame(load); r.pack(anchor="w", padx=8, pady=(6, 2))
        ttk.Label(r, text="Probe steps:").pack(side="left")
        ttk.Entry(r, textvariable=self.probe_steps, width=6).pack(side="left", padx=6)
        ttk.Button(r, text="Read load (closes jaws)", command=self._sgread).pack(side="left", padx=6)
        self.load_label = tk.Label(load, textvariable=self.load_var, font=("Segoe UI", 11, "bold"),
                                   relief="ridge", bd=2, pady=6, bg="#3a3a3a", fg="white")
        self.load_label.pack(fill="x", padx=8, pady=(4, 4))
        ttk.Label(
            load, justify="left", wraplength=560,
            text=("Run empty: load should stay ABOVE the trip level. Run with an object: load\n"
                  "should drop to/below it. Set the threshold so the trip level sits between\n"
                  "the two. (Open the jaws between probes; use a modest step count.)"),
        ).pack(anchor="w", padx=8, pady=(0, 8))

        ttk.Label(self, textvariable=self.status, wraplength=580, justify="left",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(4, 8))

    def _kv(self, parent, label, var):
        r = ttk.Frame(parent); r.pack(anchor="w", padx=8, pady=2)
        ttk.Label(r, text=label).pack(side="left")
        ttk.Label(r, textvariable=var, font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)

    # ------------------------------------------------------------- helpers

    def _ready(self):
        if not self.app.link.is_open():
            self.status.set("Not connected.")
            return False
        return True

    def _auto_enable(self):
        self.app.send("SM2 ENABLE")
        self.app.sm2_enabled_var.set("ENABLED")

    def _report(self, ok, line):
        self.status.set(line if ok else "ERROR: " + line)

    def _refresh(self, ok, line):
        self._report(ok, line)
        if ok:
            self.app.send("STATUS", log=False)

    def _enable(self):
        if self._ready():
            self._auto_enable()

    def _send(self, cmd):
        if self._ready():
            self.app.send_expect(cmd, self._report)

    def _send_refresh(self, cmd):
        if self._ready():
            self.app.send_expect(cmd, self._refresh)

    # ------------------------------------------------------------- actions

    def _open(self):
        if not self._ready():
            return
        self._auto_enable()
        self.status.set("Opening to fixed OPEN position...")
        self.app.send_expect("SM2 OPEN", self._open_done, timeout_ms=GRIP_TIMEOUT_MS)

    def _open_done(self, ok, line):
        self._refresh(ok, line)
        if ok:
            self._set_grip("OPEN  (at position)", "#3a3a3a")

    def _close(self):
        if not self._ready():
            return
        self._auto_enable()
        self.status.set("Closing until force feedback (StallGuard)...")
        self.app.send_expect("SM2 CLOSE", self._close_done, timeout_ms=GRIP_TIMEOUT_MS)

    def _close_done(self, ok, line):
        if not ok:
            self.status.set("ERROR: " + line)
            return
        self.status.set(line)
        self.app.send("STATUS", log=False)
        # Force feedback is on: grade the grip from gripped= / position=.
        text, color = self._grade_grip(line)
        self._set_grip(text, color)

    def _grade_grip(self, line):
        """Classify a CLOSE result from its 'gripped=' and 'position=' fields
        against the calibrated CLOSED cap (see TIGHT_FRAC)."""
        fields = {}
        for tok in line.split():
            if "=" in tok:
                k, _, v = tok.partition("=")
                fields[k] = v
        gripped = fields.get("gripped") == "1"
        try:
            pos = abs(int(fields.get("position", "0")))
        except ValueError:
            pos = 0
        try:
            cap = abs(int(self.app.sm2_closed_var.get()))
        except ValueError:
            cap = 0
        if not gripped:
            return ("OK  -  nothing held", "#444444")
        if cap and pos >= TIGHT_FRAC * cap:
            return ("NOT OK  -  very tight", "#b00020")
        return ("PARTIAL  -  something held", "#1e7d32")

    def _set_grip(self, text, color):
        self.grip_var.set(text)
        try:
            self.grip_label.configure(bg=color)
        except tk.TclError:
            pass

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
        self.app.send_expect("SM2 JOG {} {}".format(direction, steps), self._report, timeout_ms=GRIP_TIMEOUT_MS)

    def _mark(self, which):
        if self._ready():
            self.app.send_expect("SM2 MARK " + which, self._refresh, match="SM2 MARK")

    def _set_threshold(self):
        raw = self.sg_entry.get().strip()
        try:
            v = int(raw)
            if not (0 <= v <= 255):
                raise ValueError
        except ValueError:
            self.status.set("Threshold must be a whole number 0-255.")
            return
        if self._ready():
            self.app.send_expect("SM2 SET STALLTHRESHOLD {}".format(v), self._refresh)

    def _sgread(self):
        if not self._ready():
            return
        raw = self.probe_steps.get().strip()
        try:
            n = int(raw)
            if n < 1:
                raise ValueError
        except ValueError:
            self.status.set("Probe steps must be a positive whole number.")
            return
        self._auto_enable()
        self.status.set("Probing StallGuard (closing {} steps)...".format(n))
        self.app.send_expect("SM2 SGREAD {}".format(n), self._sgread_done, match="SM2 SGREAD", timeout_ms=60000)

    def _sgread_done(self, ok, line):
        if not ok:
            self.status.set("ERROR: " + line)
            return
        self.status.set(line)
        self.app.send("STATUS", log=False)
        f = {}
        for tok in line.split():
            if "=" in tok:
                k, _, v = tok.partition("=")
                f[k] = v
        sgmin = f.get("sgmin", "?")
        trips_at = f.get("trips_at", "?")
        thr = f.get("threshold", "?")
        self.load_var.set("load(min)={}    trips when load <= {}   (threshold {})".format(sgmin, trips_at, thr))
        try:
            would_trip = int(sgmin) <= int(trips_at)
        except ValueError:
            would_trip = False
        # red = this reading WOULD trip the grip; green = it would not
        self.load_label.configure(bg="#b00020" if would_trip else "#1e7d32")

    def _estop(self):
        self.app.send("ESTOP")
        self.status.set("ESTOP - motors disabled.")

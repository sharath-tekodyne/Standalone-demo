"""4-Jaw gripper demo - step-by-step tester.

Same board/firmware as the 2-jaw demo (SM1 platform + SM2 gripper on the
TMC2209), but a different choreography for handling test tubes. This tab lets
you fire each step of the 4-jaw sequence on its own so you can verify motion,
distances and force feedback before chaining them.

There are TWO pick modes, and the live demo ALTERNATES them cycle-to-cycle
(outside, then inside, then outside, ...):

  OUTSIDE pick  - grab a tube from the outside:  CLOSE grabs, OPEN releases
  INSIDE pick   - grab a tube from the inside:   OPENGRIP grabs, CLOSE releases
                  (OPENGRIP expands the jaws until they feel the delicate tube
                   wall and stops on it - force feedback on the open stroke)

Positions (HOME=0; MAIN and REACH are absolute step targets set below):

  Priming (once):  Find HOME -> Open jaws
  OUTSIDE pick:    MAIN -> CLOSE(grab) -> HOME -> MAIN -> OPEN(release) -> REACH
  INSIDE  pick:    CLOSE(prep) -> MAIN -> OPENGRIP(grab, force fb) -> HOME ->
                   MAIN -> CLOSE(release) -> REACH

Only the inside-grab (OPENGRIP) and the outside-grab (CLOSE) use force feedback;
the inside prep/release CLOSEs just drive the jaws fully shut (CLOSE jams at
fully-shut and reports "nothing held", which is correct there).

This tab fires each step on its own so you can verify motion, distances and the
force-feedback grips. MAIN/REACH go out as `SM1 GOTO STEPS <n>` absolute moves,
so they never disturb the 2-jaw demo's calibrated MAIN - both demos share one GUI.
"""

import tkinter as tk
from tkinter import ttk

MOVE_TIMEOUT_MS = 120000   # long platform moves (-13000 steps) take tens of seconds
GRIP_TIMEOUT_MS = 60000


class FourJawPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.main_steps = tk.StringVar(value="-13000")   # absolute target for MAIN
        self.reach_steps = tk.StringVar(value="-7000")   # absolute target for REACH
        self.opengrip_steps = tk.StringVar(value="")     # blank = firmware default (SM2_OPEN_GRIP_MAX)
        self.speed_us = tk.StringVar(value="")           # custom step period for both motors (blank = presets)
        self.status = tk.StringVar(value="Enable both axes, then test each step, or Run full demo. Force feedback: CLOSE grab and OPENGRIP grab.")
        self.grip_var = tk.StringVar(value="-  (grip result shows here)")
        self.demo_status = tk.StringVar(value="idle")
        self.demo_cycles = tk.StringVar(value="0")
        # --- full-demo loop player state ---
        self._running = False
        self._run_id = 0            # bumped each Run/Stop so stale replies are ignored
        self._queue = []            # remaining steps in the current pass
        self._body = []             # the repeating loop body (outside + inside pick)
        self._build()

    # --------------------------------------------------------------- build

    def _build(self):
        live = ttk.LabelFrame(self, text="Live (SM1 platform + SM2 gripper)")
        live.pack(fill="x", padx=10, pady=(10, 6))
        grid = ttk.Frame(live); grid.pack(fill="x", padx=8, pady=4)
        self._kv(grid, 0, 0, "SM1 enabled:", self.app.sm1_enabled_var)
        self._kv(grid, 0, 1, "SM1 position:", self.app.sm1_pos_var)
        self._kv(grid, 0, 2, "HOME switch:", self.app.home_switch_var)
        self._kv(grid, 1, 0, "SM2 enabled:", self.app.sm2_enabled_var)
        self._kv(grid, 1, 1, "SM2 position:", self.app.sm2_pos_var)
        self._kv(grid, 1, 2, "Jaw state:", self.app.gripper_state_var)
        self._kv(grid, 2, 0, "UART/StallGuard:", self.app.sm2_ready_var)
        self._kv(grid, 2, 1, "CLOSED cap:", self.app.sm2_closed_var)
        self._kv(grid, 2, 2, "SG threshold:", self.app.sm2_sgthrs_var)

        en = ttk.Frame(self)
        en.pack(fill="x", padx=10, pady=4)
        ttk.Button(en, text="Enable SM1", command=lambda: self._enable("SM1")).pack(side="left", padx=4)
        ttk.Button(en, text="Enable SM2", command=lambda: self._enable("SM2")).pack(side="left", padx=4)
        ttk.Button(en, text="Enable both", command=self._enable_both).pack(side="left", padx=4)
        ttk.Button(en, text="ESTOP", command=self._estop).pack(side="left", padx=16)

        cfg = ttk.LabelFrame(self, text="Positions (absolute steps from HOME=0)")
        cfg.pack(fill="x", padx=10, pady=6)
        row = ttk.Frame(cfg); row.pack(anchor="w", padx=8, pady=6)
        ttk.Label(row, text="MAIN:").pack(side="left")
        ttk.Entry(row, textvariable=self.main_steps, width=8).pack(side="left", padx=(4, 16))
        ttk.Label(row, text="REACH:").pack(side="left")
        ttk.Entry(row, textvariable=self.reach_steps, width=8).pack(side="left", padx=(4, 16))
        ttk.Label(row, text="Open-grip max steps:").pack(side="left")
        ttk.Entry(row, textvariable=self.opengrip_steps, width=8).pack(side="left", padx=4)
        ttk.Label(row, text="(blank = firmware default)").pack(side="left", padx=4)

        # ---- speed of BOTH motors ----
        spd = ttk.LabelFrame(self, text="Speed (both motors)")
        spd.pack(fill="x", padx=10, pady=6)
        sr = ttk.Frame(spd); sr.pack(anchor="w", padx=8, pady=6)
        ttk.Label(sr, text="Preset:").pack(side="left")
        for lvl in ("LOW", "MEDIUM", "HIGH"):
            ttk.Button(sr, text=lvl, width=8, command=lambda v=lvl: self._set_speed(v)).pack(side="left", padx=2)
        ttk.Label(sr, text="   Custom step period (us, smaller = faster):").pack(side="left", padx=(12, 2))
        ttk.Entry(sr, textvariable=self.speed_us, width=6).pack(side="left", padx=2)
        ttk.Button(sr, text="Apply us", command=self._set_speed_us).pack(side="left", padx=2)
        ttk.Label(spd, justify="left", wraplength=600, foreground="#555",
                  text=("HIGH is the fastest preset; for more, set a smaller custom us. Force-feedback\n"
                        "grabs (CLOSE / OPENGRIP) keep their own tuned grip speed, so raising this\n"
                        "speeds up the long platform moves and opens without disturbing detection.")
                  ).pack(anchor="w", padx=8, pady=(0, 6))

        # ---- run the whole demo in a loop ----
        demo = ttk.LabelFrame(self, text="Full demo (loops outside pick / inside pick until stopped)")
        demo.pack(fill="x", padx=10, pady=6)
        dr = ttk.Frame(demo); dr.pack(anchor="w", padx=8, pady=6)
        self.run_btn = ttk.Button(dr, text="▶  Run full demo (loop)", command=self._run_demo)
        self.run_btn.pack(side="left", padx=2)
        self.stop_btn = ttk.Button(dr, text="■  Stop", command=self._stop_demo, state="disabled")
        self.stop_btn.pack(side="left", padx=2)
        ttk.Label(dr, text="   Cycles:").pack(side="left", padx=(12, 2))
        ttk.Label(dr, textvariable=self.demo_cycles, font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(demo, textvariable=self.demo_status, wraplength=600, justify="left",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=8, pady=(0, 6))

        # ---- priming (run once at the start) ----
        prime = ttk.LabelFrame(self, text="Priming (run once)")
        prime.pack(fill="x", padx=10, pady=6)
        for c in range(2):
            prime.columnconfigure(c, weight=1)
        self._step(prime, 0, 0, "Find HOME", self._home)
        self._step(prime, 0, 1, "Open jaws", lambda: self._open())

        # ---- two pick modes, side by side; the live demo alternates them ----
        modes = ttk.Frame(self)
        modes.pack(fill="both", expand=True, padx=10, pady=6)
        modes.columnconfigure(0, weight=1)
        modes.columnconfigure(1, weight=1)

        out = ttk.LabelFrame(modes, text="OUTSIDE pick  (CLOSE grabs / OPEN releases)")
        out.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        out.columnconfigure(0, weight=1)
        self._step(out, 0, 0, "1  Go to MAIN (jaws open)", lambda: self._goto(self.main_steps, "MAIN"))
        self._step(out, 1, 0, "2  CLOSE - grab (force fb)", self._close_grip)
        self._step(out, 2, 0, "3  Go to HOME", lambda: self._goto_steps(0, "HOME"))
        self._step(out, 3, 0, "4  Go to MAIN", lambda: self._goto(self.main_steps, "MAIN"))
        self._step(out, 4, 0, "5  OPEN - release", lambda: self._open())
        self._step(out, 5, 0, "6  Go to REACH", lambda: self._goto(self.reach_steps, "REACH"))

        ins = ttk.LabelFrame(modes, text="INSIDE pick  (OPENGRIP grabs / CLOSE releases)")
        ins.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ins.columnconfigure(0, weight=1)
        self._step(ins, 0, 0, "1  CLOSE - jaws (prep)", self._close_grip)
        self._step(ins, 1, 0, "2  Go to MAIN", lambda: self._goto(self.main_steps, "MAIN"))
        self._step(ins, 2, 0, "3  OPENGRIP - grab & hold (force fb)", self._open_grip)
        self._step(ins, 3, 0, "4  Go to HOME", lambda: self._goto_steps(0, "HOME"))
        self._step(ins, 4, 0, "5  Go to MAIN", lambda: self._goto(self.main_steps, "MAIN"))
        self._step(ins, 5, 0, "6  CLOSE - release", self._close_grip)
        self._step(ins, 6, 0, "7  Go to REACH", lambda: self._goto(self.reach_steps, "REACH"))

        self.grip_label = tk.Label(self, textvariable=self.grip_var, font=("Segoe UI", 14, "bold"),
                                   relief="ridge", bd=2, pady=6, bg="#3a3a3a", fg="white")
        self.grip_label.pack(fill="x", padx=10, pady=(4, 4))
        ttk.Label(self, textvariable=self.status, wraplength=600, justify="left",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(2, 8))

    def _kv(self, parent, row, col, label, var):
        cell = ttk.Frame(parent); cell.grid(row=row, column=col, sticky="w", padx=8, pady=2)
        ttk.Label(cell, text=label).pack(side="left")
        ttk.Label(cell, textvariable=var, font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)

    def _step(self, parent, row, col, text, command, span=1):
        ttk.Button(parent, text=text, command=command).grid(
            row=row, column=col, columnspan=span, padx=6, pady=4, sticky="ew")

    # ------------------------------------------------------------- helpers

    def _ready(self):
        if not self.app.link.is_open():
            self.status.set("Not connected.")
            return False
        return True

    def _enable(self, axis):
        if self._ready():
            self.app.send(axis + " ENABLE")

    def _enable_both(self):
        if self._ready():
            self.app.send("SM1 ENABLE")
            self.app.send("SM2 ENABLE")
            self.status.set("Both axes enabled.")

    def _report(self, ok, line):
        self.status.set(line if ok else "ERROR: " + line)
        if ok:
            self.app.send("STATUS", log=False)

    def _parse_target(self, var, name):
        raw = var.get().strip()
        try:
            return int(raw)
        except ValueError:
            self.status.set("{} must be a whole number (may be negative).".format(name))
            return None

    # ------------------------------------------------------------- actions

    def _home(self):
        if not self._ready():
            return
        self.app.send("SM1 ENABLE")
        self.status.set("Homing to the limit switch...")
        self.app.send_expect("SM1 HOME", self._report, timeout_ms=MOVE_TIMEOUT_MS)

    def _goto(self, var, name):
        target = self._parse_target(var, name)
        if target is None or not self._ready():
            return
        self._goto_steps(target, name)

    def _goto_steps(self, target, name):
        if not self._ready():
            return
        self.app.send("SM1 ENABLE")
        self.status.set("Moving to {} ({} steps)...".format(name, target))
        self.app.send_expect("SM1 GOTO STEPS {}".format(target), self._report, timeout_ms=MOVE_TIMEOUT_MS)

    def _open(self):
        if not self._ready():
            return
        self.app.send("SM2 ENABLE")
        self.status.set("Opening the gripper...")
        self.app.send_expect("SM2 OPEN", self._report, timeout_ms=GRIP_TIMEOUT_MS)

    def _close_grip(self):
        if not self._ready():
            return
        self.app.send("SM2 ENABLE")
        self.status.set("Closing on the tube (force feedback)...")
        self.app.send_expect("SM2 CLOSE", self._grip_done, timeout_ms=GRIP_TIMEOUT_MS)

    def _open_grip(self):
        if not self._ready():
            return
        self.app.send("SM2 ENABLE")
        raw = self.opengrip_steps.get().strip()
        cmd = "SM2 OPENGRIP"
        if raw:
            try:
                n = int(raw)
                if n < 1:
                    raise ValueError
                cmd = "SM2 OPENGRIP {}".format(n)
            except ValueError:
                self.status.set("Open-grip max steps must be a positive whole number (or blank).")
                return
        self.status.set("Opening until the tube is detected (force feedback)...")
        self.app.send_expect(cmd, self._grip_done, match="SM2 OPENGRIP", timeout_ms=GRIP_TIMEOUT_MS)

    def _grip_done(self, ok, line):
        if not ok:
            self.status.set("ERROR: " + line)
            self._set_grip("ERROR", "#b00020")
            return
        self.status.set(line)
        self.app.send("STATUS", log=False)
        gripped = False
        for tok in line.split():
            if tok == "gripped=1":
                gripped = True
        if gripped:
            self._set_grip("HELD  ✓  (object detected)", "#1e7d32")
        else:
            self._set_grip("nothing held", "#444444")

    def _set_grip(self, text, color):
        self.grip_var.set(text)
        try:
            self.grip_label.configure(bg=color)
        except tk.TclError:
            pass

    # ---------------------------------------------------------- speed

    def _set_speed(self, level):
        if not self._ready():
            return
        self.app.send("SM1 SET SPEED " + level)
        self.app.send("SM2 SET SPEED " + level)
        self.status.set("Speed preset {} applied to both motors.".format(level))

    def _set_speed_us(self):
        raw = self.speed_us.get().strip()
        try:
            us = int(raw)
            if us < 100:
                raise ValueError
        except ValueError:
            self.status.set("Step period must be a whole number of us >= 100 (smaller = faster).")
            return
        if not self._ready():
            return
        self.app.send("SM1 SET SPEEDUS {}".format(us))
        self.app.send("SM2 SET SPEEDUS {}".format(us))
        self.status.set("Custom step period {} us applied to both motors.".format(us))

    # ------------------------------------------------- full-demo loop

    def _build_demo_steps(self):
        """Return (priming, body) as lists of (cmd, timeout_ms, match). `body`
        is one full alternating cycle: an outside pick then an inside pick."""
        main = self._parse_target(self.main_steps, "MAIN")
        reach = self._parse_target(self.reach_steps, "REACH")
        if main is None or reach is None:
            return None
        opengrip = "SM2 OPENGRIP"
        raw = self.opengrip_steps.get().strip()
        if raw:
            opengrip = "SM2 OPENGRIP {}".format(raw)

        def go(n):
            return ("SM1 GOTO STEPS {}".format(n), MOVE_TIMEOUT_MS, None)
        grip = GRIP_TIMEOUT_MS

        priming = [("SM1 HOME", MOVE_TIMEOUT_MS, None), ("SM2 OPEN", grip, None)]
        outside = [
            go(main), ("SM2 CLOSE", grip, None), go(0), go(main),
            ("SM2 OPEN", grip, "SM2 OPEN "), go(reach),
        ]
        inside = [
            ("SM2 CLOSE", grip, None), go(main), (opengrip, grip, "SM2 OPENGRIP"),
            go(0), go(main), ("SM2 CLOSE", grip, None), go(reach),
        ]
        return priming, outside + inside

    def _run_demo(self):
        if self._running or not self._ready():
            return
        built = self._build_demo_steps()
        if built is None:
            return
        priming, body = built
        self._body = body
        self._queue = list(priming) + list(body)
        self._running = True
        self._run_id += 1
        self.demo_cycles.set("0")
        self.app.send("SM1 ENABLE")
        self.app.send("SM2 ENABLE")
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.demo_status.set("Running full demo (homing first)...")
        self._exec_next(self._run_id)

    def _exec_next(self, rid):
        if not self._running or rid != self._run_id:
            return
        if not self._queue:
            # finished a full loop body; count it and queue the body again
            cycles = int(self.demo_cycles.get() or "0") + 1
            self.demo_cycles.set(str(cycles))
            self._queue = list(self._body)
        cmd, timeout, match = self._queue.pop(0)
        self.demo_status.set("Running: " + cmd)
        self.app.send_expect(cmd, lambda ok, line: self._step_done(ok, line, rid),
                             match=match, timeout_ms=timeout)

    def _step_done(self, ok, line, rid):
        if rid != self._run_id:
            return  # a stale reply from a stopped/previous run
        if "gripped=1" in line:
            self._set_grip("HELD  ✓  (object detected)", "#1e7d32")
        elif "gripped=0" in line:
            self._set_grip("nothing held", "#444444")
        if not self._running:
            return
        if not ok:
            self.demo_status.set("Demo STOPPED on error: " + line)
            self._finish_demo()
            return
        self.app.send("STATUS", log=False)
        self._exec_next(rid)

    def _stop_demo(self):
        if not self._running:
            return
        self._running = False
        self._run_id += 1          # invalidate any in-flight reply
        self.app.send("ESTOP")     # abort a move that is currently running
        self.demo_status.set("Demo stopped (ESTOP sent - re-enable happens on next Run).")
        self._finish_demo()

    def _finish_demo(self):
        self._running = False
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _estop(self):
        if self._running:
            self._stop_demo()
        self.app.send("ESTOP")
        self.status.set("ESTOP - motors disabled.")

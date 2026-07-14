"""Step-by-Step bring-up panel.

Two jobs, both aimed at validating a fresh rig one action at a time:

1. MAIN calibration box - jog SM1 CW/ACW by hand until the carriage is at the
   physical HOME, click "Start recording" (which zeroes the step count there),
   then keep jogging out to MAIN and click "Save as MAIN". The recorded step
   count is persisted on the Pico as the HOME->MAIN distance the demo uses.

2. Step runner - the demo cycle broken into its individual actions. Run each
   one on its own, watch the live result, and mark it working (or failed)
   before moving to the next. Every action goes through app.send_expect(), so
   the exact OK/ERR reply (or a timeout) is surfaced per step, plus a global
   pre-flight check (connected? axis enabled? demo stopped? gripper UART up?).
"""

from __future__ import annotations

import tkinter as tk

import ttkbootstrap as ttk

# (description, command, which axis it needs, reply timeout in ms)
CYCLE_STEPS = [
    ("1. Home SM1 to the limit switch", "SM1 HOME", "SM1", 180000),
    ("2. Open gripper at HOME", "SM2 OPEN", "SM2", 60000),
    ("3. Move HOME -> MAIN (gripper open)", "SM1 GOTO MAIN", "SM1", 120000),
    ("4. Move MAIN -> HOME", "SM1 GOTO HOME", "SM1", 120000),
    ("5. Close gripper at HOME", "SM2 CLOSE", "SM2", 60000),
    ("6. Move HOME -> MAIN (gripper closed)", "SM1 GOTO MAIN", "SM1", 120000),
    ("7. Move MAIN -> HOME", "SM1 GOTO HOME", "SM1", 120000),
    ("8. Open gripper at HOME", "SM2 OPEN", "SM2", 60000),
    ("9. Close gripper at HOME", "SM2 CLOSE", "SM2", 60000),
]


class StepPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.widgets = []          # controls toggled by connect/disconnect
        self._busy = False         # True while one command is awaiting its reply
        self.recording = False

        self.jog_size_var = tk.StringVar(value="100")
        self.main_steps_var = tk.StringVar(value="")
        self.cal_status_var = tk.StringVar(value="Idle - jog SM1 to HOME to begin.")
        self.error_var = tk.StringVar(value="")

        self.step_status_vars = []
        self.step_status_labels = []
        self.step_run_buttons = []
        self.step_confirm_buttons = []

        self._build()

    # ------------------------------------------------------------- build

    def _track(self, widget):
        self.widgets.append(widget)
        return widget

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=2)

        self._build_prereqs()
        self._build_calibration()
        self._build_steps()
        self._build_error_bar()

    def _build_prereqs(self):
        box = ttk.LabelFrame(self, text="Prerequisites (do these before running steps)")
        box.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")

        self._track(ttk.Button(box, text="Enable SM1", command=lambda: self._enable("SM1"))).grid(
            row=0, column=0, padx=6, pady=6, sticky="ew"
        )
        self._track(ttk.Button(box, text="Enable SM2", command=lambda: self._enable("SM2"))).grid(
            row=0, column=1, padx=6, pady=6, sticky="ew"
        )
        self._track(
            ttk.Button(box, text="Stop demo (if running)", command=lambda: self.app.send("DEMO PAUSE"))
        ).grid(row=0, column=2, padx=6, pady=6, sticky="ew")
        self._track(
            ttk.Button(box, text="ESTOP", bootstyle="danger", command=lambda: self.app.send("ESTOP"))
        ).grid(row=0, column=3, padx=6, pady=6, sticky="ew")

        self._kv(box, 1, "SM1:", self.app.sm1_enabled_var)
        self._kv(box, 2, "SM2:", self.app.sm2_enabled_var)
        self._kv(box, 3, "SM2 UART:", self.app.sm2_ready_var)
        self._kv(box, 4, "Demo running:", self.app.demo_running_var)
        self._kv(box, 5, "Home switch:", self.app.home_switch_var)

    def _build_calibration(self):
        box = ttk.LabelFrame(self, text="Calibrate MAIN position (steps from HOME)")
        box.grid(row=1, column=0, padx=8, pady=8, sticky="nsew")
        box.columnconfigure(1, weight=1)

        ttk.Label(
            box,
            justify="left",
            text=(
                "Jog SM1 by hand to the physical HOME, then Start recording\n"
                "(that zeroes the count). Keep jogging out to MAIN, then Save."
            ),
        ).grid(row=0, column=0, columnspan=3, padx=6, pady=(6, 8), sticky="w")

        ttk.Label(box, text="Jog step size:").grid(row=1, column=0, padx=6, pady=4, sticky="w")
        self._track(ttk.Entry(box, textvariable=self.jog_size_var, width=8)).grid(
            row=1, column=1, padx=6, pady=4, sticky="w"
        )

        self._track(ttk.Button(box, text="Jog ACW", command=lambda: self._jog("ACW"))).grid(
            row=2, column=0, padx=6, pady=4, sticky="ew"
        )
        self._track(ttk.Button(box, text="Jog CW", command=lambda: self._jog("CW"))).grid(
            row=2, column=1, padx=6, pady=4, sticky="ew"
        )

        self._kv(box, 3, "SM1 position (steps):", self.app.sm1_pos_var)
        self._kv(box, 4, "Current MAIN (steps):", self.app.sm1_main_var)

        self.start_rec_btn = self._track(
            ttk.Button(box, text="1) Start recording (HOME = 0)", bootstyle="info", command=self._start_recording)
        )
        self.start_rec_btn.grid(row=5, column=0, columnspan=2, padx=6, pady=(8, 4), sticky="ew")
        self.save_main_btn = self._track(
            ttk.Button(box, text="2) Save current as MAIN", bootstyle="success", command=self._save_main)
        )
        self.save_main_btn.grid(row=6, column=0, columnspan=2, padx=6, pady=4, sticky="ew")

        ttk.Separator(box).grid(row=7, column=0, columnspan=3, sticky="ew", pady=(8, 4))
        ttk.Label(box, text="Or set MAIN steps directly:").grid(
            row=8, column=0, columnspan=3, padx=6, pady=(0, 2), sticky="w"
        )
        self._track(ttk.Entry(box, textvariable=self.main_steps_var, width=10)).grid(
            row=9, column=0, padx=6, pady=4, sticky="w"
        )
        self.set_main_btn = self._track(
            ttk.Button(box, text="Set MAIN steps", command=self._set_main_direct)
        )
        self.set_main_btn.grid(row=9, column=1, padx=6, pady=4, sticky="ew")

        ttk.Label(box, textvariable=self.cal_status_var, font=("Segoe UI", 9, "bold"), wraplength=360, justify="left").grid(
            row=10, column=0, columnspan=3, padx=6, pady=(6, 6), sticky="w"
        )

    def _build_steps(self):
        box = ttk.LabelFrame(self, text="Run the cycle one step at a time")
        box.grid(row=0, column=1, rowspan=2, padx=8, pady=8, sticky="nsew")
        box.columnconfigure(0, weight=1)

        header = ttk.Frame(box)
        header.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 6))
        ttk.Label(
            header,
            text="Run a step, watch the result, then physically confirm it worked.",
            justify="left",
        ).grid(row=0, column=0, sticky="w")
        self._track(ttk.Button(header, text="Reset all", command=self._reset_steps)).grid(row=0, column=1, padx=8)

        for i, (desc, cmd, axis, _timeout) in enumerate(CYCLE_STEPS):
            row = ttk.Frame(box)
            row.grid(row=i + 1, column=0, sticky="ew", padx=4, pady=2)
            row.columnconfigure(0, weight=1)

            ttk.Label(row, text=f"{desc}  [{cmd}]").grid(row=0, column=0, sticky="w")

            run_btn = self._track(ttk.Button(row, text="Run", width=6, command=lambda idx=i: self._run_step(idx)))
            run_btn.grid(row=0, column=1, padx=3)
            self.step_run_buttons.append(run_btn)

            status_var = tk.StringVar(value="pending")
            self.step_status_vars.append(status_var)
            status_lbl = ttk.Label(row, textvariable=status_var, width=26, anchor="w")
            status_lbl.grid(row=0, column=2, padx=3)
            self.step_status_labels.append(status_lbl)

            confirm = self._track(
                ttk.Button(row, text="OK", width=4, bootstyle="success-outline", command=lambda idx=i: self._confirm_step(idx, True))
            )
            confirm.grid(row=0, column=3, padx=2)
            fail = self._track(
                ttk.Button(row, text="Fail", width=5, bootstyle="danger-outline", command=lambda idx=i: self._confirm_step(idx, False))
            )
            fail.grid(row=0, column=4, padx=2)
            self.step_confirm_buttons.append((confirm, fail))

    def _build_error_bar(self):
        self.error_label = ttk.Label(
            self,
            textvariable=self.error_var,
            bootstyle="danger-inverse",
            anchor="w",
            wraplength=1080,
            justify="left",
        )
        self.error_label.grid(row=2, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="ew")

    def _kv(self, parent, row, label, var):
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=6, pady=2, sticky="w")
        ttk.Label(parent, textvariable=var, font=("Segoe UI", 9, "bold")).grid(
            row=row, column=1, columnspan=3, padx=6, pady=2, sticky="w"
        )

    # --------------------------------------------------------- pre-flight

    def _clear_error(self):
        self.error_var.set("")

    def _fail(self, message):
        """Surface a hard error prominently and log it."""
        self.error_var.set("ERROR: " + message)
        self.app.log_event("ERR", "step-panel: " + message)

    def _preflight(self, need_axis=None):
        """Return True if it is safe to send a motion command; else explain."""
        if not self.app.client.is_connected():
            self._fail("Not connected to the Pico. Use the Connection bar first.")
            return False
        if self._busy:
            self._fail("A command is still running - wait for it to finish (or time out).")
            return False
        if self.app.demo_running_var.get() == "running":
            self._fail("The automatic demo is running. Click 'Stop demo (if running)' first.")
            return False
        if need_axis == "SM1" and self.app.sm1_enabled_var.get() != "ENABLED":
            self._fail("SM1 is disabled. Click 'Enable SM1' in Prerequisites first.")
            return False
        if need_axis == "SM2":
            if self.app.sm2_enabled_var.get() != "ENABLED":
                self._fail("SM2 is disabled. Click 'Enable SM2' in Prerequisites first.")
                return False
            if self.app.sm2_ready_var.get() != "ready":
                self._fail("SM2 UART/StallGuard is not ready (check the TMC2209 wiring/power).")
                return False
        return True

    def _validated_jog_size(self):
        raw = self.jog_size_var.get().strip()
        try:
            size = int(raw)
        except ValueError:
            self._fail(f"Jog step size '{raw}' is not a whole number.")
            return None
        if size < 1:
            self._fail("Jog step size must be at least 1.")
            return None
        return size

    def _set_busy(self, busy):
        self._busy = busy
        state = ["disabled"] if busy else ["!disabled"]
        for btn in self.step_run_buttons:
            btn.state(state)
        for btn in (self.start_rec_btn, self.save_main_btn, self.set_main_btn):
            btn.state(state)

    # ------------------------------------------------------ calibration

    def _enable(self, axis):
        self._clear_error()
        if not self.app.client.is_connected():
            self._fail("Not connected to the Pico.")
            return
        self.app.send(f"{axis} ENABLE")

    def _jog(self, direction):
        self._clear_error()
        if not self._preflight(need_axis="SM1"):
            return
        size = self._validated_jog_size()
        if size is None:
            return
        self._set_busy(True)

        def done(ok, line):
            self._set_busy(False)
            if ok:
                self.cal_status_var.set(
                    ("Recording... " if self.recording else "")
                    + f"jogged {direction} {size} - see SM1 position above."
                )
            else:
                self._fail(f"Jog {direction} failed: {line}")

        self.app.send_expect(f"SM1 JOG {direction} {size}", done, timeout_ms=60000)

    def _start_recording(self):
        self._clear_error()
        if not self._preflight(need_axis="SM1"):
            return
        self._set_busy(True)

        def done(ok, line):
            self._set_busy(False)
            if ok:
                self.recording = True
                self.cal_status_var.set("Recording started (HOME = 0). Jog out to MAIN, then Save.")
            else:
                self._fail(f"Could not zero HOME: {line}")

        # MARK HOME zeroes the running step count at the current position.
        self.app.send_expect("SM1 MARK HOME", done, timeout_ms=15000)

    def _save_main(self):
        self._clear_error()
        if not self.recording:
            self._fail("Start recording first (jog to HOME, then '1) Start recording').")
            return
        if not self._preflight():
            return
        self._set_busy(True)

        def done(ok, line):
            self._set_busy(False)
            if ok:
                self.recording = False
                self.cal_status_var.set(
                    f"Saved MAIN = {self.app.sm1_pos_var.get()} steps. Verify 'Current MAIN' above updated."
                )
                self.app.send("CAL STATUS")
            else:
                self._fail(f"Could not save MAIN: {line}")

        # MARK MAIN records the current step count as the persisted MAIN offset.
        self.app.send_expect("SM1 MARK MAIN", done, match="SM1 MARK MAIN", timeout_ms=15000)

    def _set_main_direct(self):
        self._clear_error()
        raw = self.main_steps_var.get().strip()
        try:
            value = int(raw)
        except ValueError:
            self._fail(f"MAIN steps '{raw}' is not a whole number.")
            return
        if value == 0:
            self._fail("MAIN steps cannot be 0 (that is HOME).")
            return
        if not self._preflight():
            return
        self._set_busy(True)

        def done(ok, line):
            self._set_busy(False)
            if ok:
                self.cal_status_var.set(f"MAIN set to {value} steps. Verify 'Current MAIN' above updated.")
                self.app.send("CAL STATUS")
            else:
                self._fail(f"Could not set MAIN steps: {line}")

        self.app.send_expect(f"SM1 SET MAINSTEPS {value}", done, timeout_ms=15000)

    # ------------------------------------------------------- step runner

    def _set_step_status(self, idx, text, bootstyle):
        self.step_status_vars[idx].set(text)
        try:
            self.step_status_labels[idx].configure(bootstyle=bootstyle)
        except tk.TclError:
            pass

    def _run_step(self, idx):
        self._clear_error()
        desc, cmd, axis, timeout = CYCLE_STEPS[idx]
        if not self._preflight(need_axis=axis):
            self._set_step_status(idx, "blocked (see error)", "warning")
            return
        self._set_busy(True)
        self._set_step_status(idx, "running...", "info")

        def done(ok, line):
            self._set_busy(False)
            if ok:
                self._set_step_status(idx, "ran OK - confirm?", "success")
            else:
                self._set_step_status(idx, "ERROR", "danger")
                self._fail(f"Step {idx + 1} ({cmd}) failed: {line}")

        self.app.send_expect(cmd, done, timeout_ms=timeout)

    def _confirm_step(self, idx, working):
        if working:
            self._set_step_status(idx, "CONFIRMED working", "success")
        else:
            self._set_step_status(idx, "marked FAILED", "danger")

    def _reset_steps(self):
        self._clear_error()
        for idx in range(len(CYCLE_STEPS)):
            self._set_step_status(idx, "pending", "secondary")

    # ---------------------------------------------------- enable/disable

    def set_enabled(self, enabled):
        state = ["!disabled"] if enabled else ["disabled"]
        for widget in self.widgets:
            widget.state(state)
        if not enabled:
            self.recording = False

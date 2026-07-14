"""Start/Pause/Resume/Reset controls for the repeating demo cycle, plus a
live view of the persisted phase, gripper state, and cycle count.

The GUI's "interrupt" is the Pause button - it just sends DEMO PAUSE. The
bridge always finishes the in-flight chunk of motion first, then halts and
keeps its exact phase/position, so Resume always continues from there
rather than restarting the loop. The physical push-button on the Pico does
the same thing (latching toggle: press to pause, press again to resume) and
also starts the cycle on its first press - watch the Pause button indicator
below to see its live state.
"""

from __future__ import annotations

import ttkbootstrap as ttk


class DemoPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.widgets = []
        self._build()

    def _track(self, widget):
        self.widgets.append(widget)
        return widget

    def _build(self):
        self.columnconfigure(0, weight=1)

        controls = ttk.LabelFrame(self, text="Cycle Control")
        controls.grid(row=0, column=0, padx=8, pady=8, sticky="ew")

        self._track(ttk.Button(controls, text="Start", command=lambda: self.app.send("DEMO START"))).grid(
            row=0, column=0, padx=8, pady=8
        )
        self._track(ttk.Button(controls, text="Pause (Interrupt)", command=lambda: self.app.send("DEMO PAUSE"))).grid(
            row=0, column=1, padx=8, pady=8
        )
        self._track(ttk.Button(controls, text="Resume", command=lambda: self.app.send("DEMO RESUME"))).grid(
            row=0, column=2, padx=8, pady=8
        )
        self._track(ttk.Button(controls, text="Reset", command=self._confirm_reset)).grid(row=0, column=3, padx=8, pady=8)
        self._track(ttk.Button(controls, text="EMERGENCY STOP", command=lambda: self.app.send("ESTOP"), bootstyle="danger")).grid(
            row=0, column=4, padx=8, pady=8
        )

        status = ttk.LabelFrame(self, text="Live Cycle Status")
        status.grid(row=1, column=0, padx=8, pady=8, sticky="ew")
        for col in range(2):
            status.columnconfigure(col, weight=1)

        self._status_row(status, 0, "Phase:", self.app.demo_phase_var)
        self._status_row(status, 1, "Running:", self.app.demo_running_var)
        self._status_row(status, 2, "Cycle count:", self.app.cycle_count_var)
        self._status_row(status, 3, "Gripper state:", self.app.gripper_state_var)
        self._status_row(status, 4, "SM1 position (steps):", self.app.sm1_pos_var)
        self._status_row(status, 5, "SM2 position (steps):", self.app.sm2_pos_var)
        self._status_row(status, 6, "Home switch:", self.app.home_switch_var)
        self._status_row(status, 7, "Pause button:", self.app.pause_btn_var)

        self.attention_banner = ttk.Label(
            self,
            text="",
            font=("Segoe UI", 11, "bold"),
            bootstyle="danger-inverse",
            anchor="center",
        )
        self.attention_banner.grid(row=2, column=0, padx=8, pady=8, sticky="ew")
        self._update_attention_banner()

        # Repaint the banner whenever needs_attention flips.
        self.app.needs_attention_var.trace_add("write", lambda *_: self._update_attention_banner())

    def _status_row(self, parent, row, label, var):
        ttk.Label(parent, text=label).grid(row=row, column=0, padx=8, pady=4, sticky="w")
        ttk.Label(parent, textvariable=var, font=("Segoe UI", 10, "bold")).grid(row=row, column=1, padx=8, pady=4, sticky="w")

    def _update_attention_banner(self):
        if self.app.needs_attention_var.get():
            self.attention_banner.configure(
                text="NEEDS ATTENTION: the demo hit a fault and auto-paused. "
                "Check the Pico Console, then click Resume."
            )
        else:
            self.attention_banner.configure(text="")

    def _confirm_reset(self):
        from tkinter import messagebox

        if messagebox.askyesno(
            "Reset demo",
            "This stops the demo and clears its progress back to 'not started' "
            "(calibration is kept). Continue?",
        ):
            self.app.send("DEMO RESET")

    def set_enabled(self, enabled):
        state = ["!disabled"] if enabled else ["disabled"]
        for widget in self.widgets:
            widget.state(state)

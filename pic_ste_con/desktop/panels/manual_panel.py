"""Manual jog/test controls for SM1 (platform) and SM2 (gripper).

These talk to the bridge directly (SM1 JOG, SM2 OPEN, etc.) and are only
meant for bring-up/testing - the bridge itself refuses them while the demo
cycle is running (see require_demo_idle() in firmware/main.py), and refuses
any actual motion command unless that axis is Enabled first (see
require_sm1_enabled()/require_sm2_enabled()) - Stop/Disable now genuinely
holds until you click Enable again.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as ttk

import protocol


class ManualPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.widgets = []

        self.sm1_speed_var = tk.StringVar(value=protocol.DEFAULT_SPEED)
        self.sm1_torque_var = tk.StringVar(value=protocol.DEFAULT_TORQUE)
        self.sm1_jog_steps_var = tk.StringVar(value="200")
        self.sm1_speed_us_var = tk.StringVar(value="")
        self.sm1_goto_steps_var = tk.StringVar(value="0")

        self.sm2_speed_var = tk.StringVar(value=protocol.DEFAULT_SPEED)
        self.sm2_torque_var = tk.StringVar(value=protocol.DEFAULT_TORQUE)
        self.sm2_jog_steps_var = tk.StringVar(value="50")
        self.sm2_sgthrs_var = tk.StringVar(value=str(protocol.DEFAULT_STALLGUARD_THRESHOLD))
        self.sm2_speed_us_var = tk.StringVar(value="")
        self.sm2_goto_steps_var = tk.StringVar(value="0")

        self._build()

    def _track(self, widget):
        self.widgets.append(widget)
        return widget

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        sm1 = ttk.LabelFrame(self, text="SM1 - Platform Axis (TMC2208)")
        sm1.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        self._build_sm1(sm1)

        sm2 = ttk.LabelFrame(self, text="SM2 - Gripper Axis (TMC2209, StallGuard)")
        sm2.grid(row=0, column=1, padx=8, pady=8, sticky="nsew")
        self._build_sm2(sm2)

    def _confirm_freedrive(self, axis_label, command):
        if messagebox.askyesno(
            f"Freedrive {axis_label}",
            f"This de-energizes {axis_label} so you can move it by hand.\n\n"
            "Position tracking will no longer match reality once you do - "
            "re-run calibration (Mark commands) for this axis before "
            "starting or resuming the demo.",
        ):
            self.app.send(command)

    def _build_sm1(self, frame):
        row = 0
        ttk.Label(frame, text="Status:").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(frame, textvariable=self.app.sm1_enabled_var, font=("Segoe UI", 10, "bold")).grid(
            row=row, column=1, padx=6, pady=6, sticky="w"
        )
        row += 1

        self._track(ttk.Button(frame, text="Enable", command=lambda: self.app.send("SM1 ENABLE"))).grid(
            row=row, column=0, padx=6, pady=6
        )
        self._track(ttk.Button(frame, text="Disable", command=lambda: self.app.send("SM1 DISABLE"))).grid(
            row=row, column=1, padx=6, pady=6
        )
        self._track(ttk.Button(frame, text="Stop", command=lambda: self.app.send("SM1 STOP"), bootstyle="danger")).grid(
            row=row, column=2, padx=6, pady=6
        )
        row += 1

        self._track(
            ttk.Button(frame, text="Freedrive (move by hand)", command=lambda: self._confirm_freedrive("SM1", "SM1 FREEDRIVE"))
        ).grid(row=row, column=0, columnspan=3, padx=6, pady=6, sticky="ew")
        row += 1

        ttk.Label(frame, text="Speed preset").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(ttk.Combobox(frame, textvariable=self.sm1_speed_var, values=protocol.SPEED_LEVELS, state="readonly", width=10)).grid(
            row=row, column=1, padx=6, pady=6, sticky="w"
        )
        self._track(
            ttk.Button(frame, text="Apply", command=lambda: self.app.send(f"SM1 SET SPEED {self.sm1_speed_var.get()}"))
        ).grid(row=row, column=2, padx=6, pady=6)
        row += 1

        ttk.Label(frame, text="Torque").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(ttk.Combobox(frame, textvariable=self.sm1_torque_var, values=protocol.TORQUE_LEVELS, state="readonly", width=10)).grid(
            row=row, column=1, padx=6, pady=6, sticky="w"
        )
        self._track(
            ttk.Button(frame, text="Apply", command=lambda: self.app.send(f"SM1 SET TORQUE {self.sm1_torque_var.get()}"))
        ).grid(row=row, column=2, padx=6, pady=6)
        row += 1

        ttk.Label(frame, text="Manual speed (us/step, lower=faster)").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(ttk.Entry(frame, textvariable=self.sm1_speed_us_var, width=10)).grid(row=row, column=1, padx=6, pady=6, sticky="w")
        self._track(
            ttk.Button(frame, text="Apply", command=lambda: self.app.send(f"SM1 SET SPEEDUS {self.sm1_speed_us_var.get()}"))
        ).grid(row=row, column=2, padx=6, pady=6)
        row += 1
        self._track(ttk.Button(frame, text="Back to preset speed (Auto)", command=lambda: self.app.send("SM1 SET SPEEDUS AUTO"))).grid(
            row=row, column=0, columnspan=2, padx=6, pady=(0, 6), sticky="w"
        )
        ttk.Label(frame, text="Active:").grid(row=row, column=2, padx=(6, 2), pady=(0, 6), sticky="e")
        row += 1
        ttk.Label(frame, textvariable=self.app.sm1_speed_us_var, font=("Segoe UI", 9, "bold")).grid(
            row=row - 1, column=3, padx=(0, 6), pady=(0, 6), sticky="w"
        )

        ttk.Label(frame, text="Jog steps").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(ttk.Entry(frame, textvariable=self.sm1_jog_steps_var, width=10)).grid(row=row, column=1, padx=6, pady=6, sticky="w")
        row += 1

        self._track(
            ttk.Button(frame, text="Jog ACW", command=lambda: self.app.send(f"SM1 JOG ACW {self.sm1_jog_steps_var.get()}"))
        ).grid(row=row, column=0, padx=6, pady=6)
        self._track(
            ttk.Button(frame, text="Jog CW", command=lambda: self.app.send(f"SM1 JOG CW {self.sm1_jog_steps_var.get()}"))
        ).grid(row=row, column=1, padx=6, pady=6)
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=6)
        row += 1

        ttk.Label(frame, text="Home to the limit switch, or go to a position:").grid(row=row, column=0, columnspan=3, padx=6, sticky="w")
        row += 1
        self._track(ttk.Button(frame, text="Home to switch", command=lambda: self.app.send("SM1 HOME"))).grid(
            row=row, column=0, padx=6, pady=6
        )
        self._track(ttk.Button(frame, text="Go HOME", command=lambda: self.app.send("SM1 GOTO HOME"))).grid(
            row=row, column=1, padx=6, pady=6
        )
        self._track(ttk.Button(frame, text="Go MAIN", command=lambda: self.app.send("SM1 GOTO MAIN"))).grid(
            row=row, column=2, padx=6, pady=6
        )
        row += 1

        ttk.Label(frame, text="Or go to an exact step count:").grid(row=row, column=0, columnspan=3, padx=6, sticky="w")
        row += 1
        self._track(ttk.Entry(frame, textvariable=self.sm1_goto_steps_var, width=10)).grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(
            ttk.Button(frame, text="Go", command=lambda: self.app.send(f"SM1 GOTO STEPS {self.sm1_goto_steps_var.get()}"))
        ).grid(row=row, column=1, padx=6, pady=6, sticky="w")
        row += 1

        ttk.Label(frame, text="Position (steps):").grid(row=row, column=0, padx=6, pady=(10, 6), sticky="w")
        ttk.Label(frame, textvariable=self.app.sm1_pos_var).grid(row=row, column=1, padx=6, pady=(10, 6), sticky="w")

    def _build_sm2(self, frame):
        row = 0
        ttk.Label(frame, text="Status:").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(frame, textvariable=self.app.sm2_enabled_var, font=("Segoe UI", 10, "bold")).grid(
            row=row, column=1, padx=6, pady=6, sticky="w"
        )
        row += 1

        self._track(ttk.Button(frame, text="Enable", command=lambda: self.app.send("SM2 ENABLE"))).grid(
            row=row, column=0, padx=6, pady=6
        )
        self._track(ttk.Button(frame, text="Disable", command=lambda: self.app.send("SM2 DISABLE"))).grid(
            row=row, column=1, padx=6, pady=6
        )
        self._track(ttk.Button(frame, text="Stop", command=lambda: self.app.send("SM2 STOP"), bootstyle="danger")).grid(
            row=row, column=2, padx=6, pady=6
        )
        row += 1

        self._track(
            ttk.Button(frame, text="Freedrive (move by hand)", command=lambda: self._confirm_freedrive("SM2", "SM2 FREEDRIVE"))
        ).grid(row=row, column=0, columnspan=3, padx=6, pady=6, sticky="ew")
        row += 1

        ttk.Label(frame, text="Speed preset").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(ttk.Combobox(frame, textvariable=self.sm2_speed_var, values=protocol.SPEED_LEVELS, state="readonly", width=10)).grid(
            row=row, column=1, padx=6, pady=6, sticky="w"
        )
        self._track(
            ttk.Button(frame, text="Apply", command=lambda: self.app.send(f"SM2 SET SPEED {self.sm2_speed_var.get()}"))
        ).grid(row=row, column=2, padx=6, pady=6)
        row += 1

        ttk.Label(frame, text="Torque (grip force)").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(ttk.Combobox(frame, textvariable=self.sm2_torque_var, values=protocol.TORQUE_LEVELS, state="readonly", width=10)).grid(
            row=row, column=1, padx=6, pady=6, sticky="w"
        )
        self._track(
            ttk.Button(frame, text="Apply", command=lambda: self.app.send(f"SM2 SET TORQUE {self.sm2_torque_var.get()}"))
        ).grid(row=row, column=2, padx=6, pady=6)
        row += 1

        ttk.Label(frame, text="Manual speed (us/step, lower=faster)").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(ttk.Entry(frame, textvariable=self.sm2_speed_us_var, width=10)).grid(row=row, column=1, padx=6, pady=6, sticky="w")
        self._track(
            ttk.Button(frame, text="Apply", command=lambda: self.app.send(f"SM2 SET SPEEDUS {self.sm2_speed_us_var.get()}"))
        ).grid(row=row, column=2, padx=6, pady=6)
        row += 1
        self._track(ttk.Button(frame, text="Back to preset speed (Auto)", command=lambda: self.app.send("SM2 SET SPEEDUS AUTO"))).grid(
            row=row, column=0, columnspan=2, padx=6, pady=(0, 6), sticky="w"
        )
        ttk.Label(frame, text="Active:").grid(row=row, column=2, padx=(6, 2), pady=(0, 6), sticky="e")
        row += 1
        ttk.Label(frame, textvariable=self.app.sm2_speed_us_var, font=("Segoe UI", 9, "bold")).grid(
            row=row - 1, column=3, padx=(0, 6), pady=(0, 6), sticky="w"
        )

        ttk.Label(frame, text="StallGuard threshold (0-255)").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(ttk.Entry(frame, textvariable=self.sm2_sgthrs_var, width=10)).grid(row=row, column=1, padx=6, pady=6, sticky="w")
        self._track(
            ttk.Button(frame, text="Apply", command=lambda: self.app.send(f"SM2 SET STALLTHRESHOLD {self.sm2_sgthrs_var.get()}"))
        ).grid(row=row, column=2, padx=6, pady=6)
        row += 1

        ttk.Label(frame, text="Jog steps").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(ttk.Entry(frame, textvariable=self.sm2_jog_steps_var, width=10)).grid(row=row, column=1, padx=6, pady=6, sticky="w")
        row += 1

        self._track(
            ttk.Button(frame, text="Jog Open dir", command=lambda: self.app.send(f"SM2 JOG ACW {self.sm2_jog_steps_var.get()}"))
        ).grid(row=row, column=0, padx=6, pady=6)
        self._track(
            ttk.Button(frame, text="Jog Close dir", command=lambda: self.app.send(f"SM2 JOG CW {self.sm2_jog_steps_var.get()}"))
        ).grid(row=row, column=1, padx=6, pady=6)
        row += 1

        ttk.Separator(frame).grid(row=row, column=0, columnspan=3, sticky="ew", pady=6)
        row += 1

        self._track(ttk.Button(frame, text="OPEN", command=lambda: self.app.send("SM2 OPEN"))).grid(row=row, column=0, padx=6, pady=6)
        self._track(ttk.Button(frame, text="CLOSE (verify grip)", command=lambda: self.app.send("SM2 CLOSE"))).grid(
            row=row, column=1, columnspan=2, padx=6, pady=6
        )
        row += 1

        ttk.Label(frame, text="Or go to an exact jaw step count:").grid(row=row, column=0, columnspan=3, padx=6, sticky="w")
        row += 1
        self._track(ttk.Entry(frame, textvariable=self.sm2_goto_steps_var, width=10)).grid(row=row, column=0, padx=6, pady=6, sticky="w")
        self._track(
            ttk.Button(frame, text="Go", command=lambda: self.app.send(f"SM2 GOTO STEPS {self.sm2_goto_steps_var.get()}"))
        ).grid(row=row, column=1, padx=6, pady=6, sticky="w")
        row += 1

        ttk.Label(frame, text="Position (steps):").grid(row=row, column=0, padx=6, pady=(10, 6), sticky="w")
        ttk.Label(frame, textvariable=self.app.sm2_pos_var).grid(row=row, column=1, padx=6, pady=(10, 6), sticky="w")
        row += 1
        ttk.Label(frame, text="Gripper state:").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(frame, textvariable=self.app.gripper_state_var).grid(row=row, column=1, padx=6, pady=6, sticky="w")
        row += 1
        ttk.Label(frame, text="SM2 UART link:").grid(row=row, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(frame, textvariable=self.app.sm2_ready_var).grid(row=row, column=1, padx=6, pady=6, sticky="w")

    def set_enabled(self, enabled):
        state = ["!disabled"] if enabled else ["disabled"]
        for widget in self.widgets:
            widget.state(state)

"""Bridge diagnostics: raw command entry, debug toggle, and a smoke test."""

from __future__ import annotations

import threading
import time
import tkinter as tk

import ttkbootstrap as ttk


SELF_TEST_COMMANDS = [
    "PING",
    "VERSION",
    "STATUS",
    "CAL STATUS",
]


class DiagnosticsPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.widgets = []
        self.command_var = tk.StringVar(value="")
        self._build()

    def _track(self, widget):
        self.widgets.append(widget)
        return widget

    def _build(self):
        self.columnconfigure(0, weight=1)

        quick = ttk.LabelFrame(self, text="Bridge Queries")
        quick.grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        self._track(ttk.Button(quick, text="Ping", command=lambda: self.app.send("PING"))).grid(row=0, column=0, padx=6, pady=6)
        self._track(ttk.Button(quick, text="Version", command=lambda: self.app.send("VERSION"))).grid(row=0, column=1, padx=6, pady=6)
        self._track(ttk.Button(quick, text="Help", command=lambda: self.app.send("HELP"))).grid(row=0, column=2, padx=6, pady=6)
        self._track(ttk.Button(quick, text="Status", command=lambda: self.app.send("STATUS"))).grid(row=0, column=3, padx=6, pady=6)
        self._track(ttk.Button(quick, text="Stats", command=lambda: self.app.send("STATS"))).grid(row=0, column=4, padx=6, pady=6)
        self._track(ttk.Button(quick, text="Reset Stats", command=lambda: self.app.send("RESETSTATS"))).grid(
            row=0, column=5, padx=6, pady=6
        )
        self._track(ttk.Button(quick, text="Run Self Test", command=self._run_self_test)).grid(row=0, column=6, padx=6, pady=6)

        ttk.Checkbutton(quick, text="Bridge debug log", variable=self.app.debug_var, command=self._set_bridge_debug).grid(
            row=1, column=0, columnspan=2, padx=6, pady=6, sticky="w"
        )
        ttk.Checkbutton(quick, text="Auto-scroll console", variable=self.app.auto_scroll_var).grid(
            row=1, column=2, columnspan=2, padx=6, pady=6, sticky="w"
        )
        ttk.Button(quick, text="Clear Console", command=self.app.clear_console).grid(row=1, column=4, padx=6, pady=6, sticky="w")

        manual = ttk.LabelFrame(self, text="Manual Command")
        manual.grid(row=1, column=0, padx=8, pady=8, sticky="ew")
        manual.columnconfigure(0, weight=1)
        entry = self._track(ttk.Entry(manual, textvariable=self.command_var))
        entry.grid(row=0, column=0, padx=6, pady=8, sticky="ew")
        entry.bind("<Return>", lambda _event: self._send_manual())
        self._track(ttk.Button(manual, text="Send", command=self._send_manual)).grid(row=0, column=1, padx=6, pady=8)

        ttk.Label(
            self,
            text=(
                "Full protocol reference: PING / VERSION / HELP / STATUS / STATS / RESETSTATS / "
                "DEBUG ON|OFF / ESTOP / SM1 ENABLE|DISABLE|STOP|FREEDRIVE|SET|JOG|GOTO|MARK / "
                "SM2 ENABLE|DISABLE|STOP|FREEDRIVE|SET|JOG|OPEN|CLOSE|GOTO|MARK / DEMO ... / CAL ...\n"
                "Note: the once-a-second background STATUS poll that keeps the live panels updated is not "
                "written to this console (to avoid a scrolling wall of identical lines) - Status/Stats clicked "
                "here, and everything else, still shows up normally."
            ),
            wraplength=900,
            justify="left",
        ).grid(row=2, column=0, padx=8, pady=8, sticky="w")

    def _set_bridge_debug(self):
        self.app.send("DEBUG {}".format("ON" if self.app.debug_var.get() else "OFF"))

    def _send_manual(self):
        command = self.command_var.get().strip()
        if not command:
            return
        self.app.send(command)
        self.command_var.set("")

    def _run_self_test(self):
        def worker():
            self.app.log_event("APP", "Self test started")
            for command in SELF_TEST_COMMANDS:
                self.app.send(command)
                time.sleep(0.2)
            self.app.log_event("APP", "Self test completed")
            self.app.root.after(0, lambda: self.app.set_status("Self test commands sent"))

        threading.Thread(target=worker, daemon=True).start()

    def set_enabled(self, enabled):
        state = ["!disabled"] if enabled else ["disabled"]
        for widget in self.widgets:
            widget.state(state)

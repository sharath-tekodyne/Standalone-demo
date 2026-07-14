"""Serial port selection and connect/disconnect controls."""

from __future__ import annotations

import ttkbootstrap as ttk


class ConnectionPanel(ttk.LabelFrame):
    def __init__(self, parent, app):
        super().__init__(parent, text="Connection")
        self.app = app
        self._build()

    def _build(self):
        for col in range(8):
            self.columnconfigure(col, weight=1 if col in (1, 4, 6) else 0)

        ttk.Label(self, text="Serial Port").grid(row=0, column=0, padx=8, pady=8, sticky="w")
        self.port_combo = ttk.Combobox(self, textvariable=self.app.port_var, values=[], state="readonly", width=32)
        self.port_combo.grid(row=0, column=1, padx=8, pady=8, sticky="w")

        ttk.Button(self, text="Refresh", command=self.app._refresh_ports).grid(row=0, column=2, padx=8, pady=8)
        ttk.Checkbutton(self, text="Auto-refresh", variable=self.app.auto_refresh_var).grid(row=0, column=3, padx=8, pady=8)

        ttk.Label(self, text="Baud").grid(row=0, column=4, padx=8, pady=8, sticky="w")
        ttk.Entry(self, textvariable=self.app.baud_var, width=10).grid(row=0, column=5, padx=8, pady=8, sticky="w")

        self.connect_btn = ttk.Button(self, text="Connect", command=self.app.connect)
        self.connect_btn.grid(row=0, column=6, padx=8, pady=8)
        self.disconnect_btn = ttk.Button(self, text="Disconnect", command=self.app.disconnect, state="disabled")
        self.disconnect_btn.grid(row=0, column=7, padx=8, pady=8)

        ttk.Checkbutton(self, text="Auto-connect", variable=self.app.auto_connect_var).grid(
            row=1, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="w"
        )
        ttk.Label(self, textvariable=self.app.port_status_var).grid(row=1, column=2, columnspan=2, padx=8, pady=(0, 8), sticky="w")
        ttk.Label(self, textvariable=self.app.session_path_var, wraplength=520).grid(
            row=1, column=4, columnspan=4, padx=8, pady=(0, 8), sticky="w"
        )

    def set_port_values(self, labels):
        self.port_combo["values"] = labels

    def set_connected_state(self, connected):
        self.connect_btn.state(["disabled"] if connected else ["!disabled"])
        self.disconnect_btn.state(["!disabled"] if connected else ["disabled"])

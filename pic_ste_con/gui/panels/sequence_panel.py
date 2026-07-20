"""Sequence Builder (GUI-played custom demo).

Build your own ordered list of steps from the actions the rig already supports,
then Run it: the PC sends each command, waits for it to finish, then does the
next. Wait steps are a GUI timer. Repeat runs the whole list N times (or forever
until Stop). Pause takes effect at the next step boundary. Save/Load keeps named
sequences as JSON.

No firmware change - it just replays the existing SM1/SM2/wait commands.
"""

import json
import tkinter as tk
from tkinter import ttk, filedialog

# ready-made, no-parameter actions: (button label, command, reply timeout ms)
QUICK_ACTIONS = [
    ("Find HOME", "SM1 HOME", 180000),
    ("Go HOME", "SM1 GOTO HOME", 120000),
    ("Go MAIN", "SM1 GOTO MAIN", 120000),
    ("Open gripper", "SM2 OPEN", 60000),
    ("Close gripper", "SM2 CLOSE", 60000),
]


class SequencePanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.steps = []          # list of dicts: {kind:'CMD'|'WAIT', label, cmd, ms, timeout}

        # player state
        self._run = False
        self._paused = False
        self._idx = 0
        self._loops_done = 0
        self._loops_target = None   # None = infinite
        self._wait_handle = None

        self.wait_ms = tk.StringVar(value="500")
        self.jog_axis = tk.StringVar(value="SM1")
        self.jog_dir = tk.StringVar(value="CW")
        self.jog_steps = tk.StringVar(value="200")
        self.goto_steps = tk.StringVar(value="0")
        self.repeat = tk.StringVar(value="1")
        self.status = tk.StringVar(value="Build a sequence, then Run. (Repeat 0 = loop until Stop.)")

        self._build()

    # ------------------------------------------------------------- build

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        # ---- add-step palette (left) ----
        add = ttk.LabelFrame(self, text="Add step")
        add.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        for i, (label, cmd, timeout) in enumerate(QUICK_ACTIONS):
            ttk.Button(add, text=label, command=lambda l=label, c=cmd, t=timeout: self._add_cmd(l, c, t)).grid(
                row=i // 2, column=i % 2, sticky="ew", padx=4, pady=3)
        add.columnconfigure(0, weight=1); add.columnconfigure(1, weight=1)

        r = 3
        ttk.Separator(add).grid(row=r, column=0, columnspan=2, sticky="ew", pady=6); r += 1
        wf = ttk.Frame(add); wf.grid(row=r, column=0, columnspan=2, sticky="ew", padx=4, pady=2); r += 1
        ttk.Label(wf, text="Wait").pack(side="left")
        ttk.Entry(wf, textvariable=self.wait_ms, width=7).pack(side="left", padx=4)
        ttk.Label(wf, text="ms").pack(side="left")
        ttk.Button(wf, text="Add Wait", command=self._add_wait).pack(side="left", padx=6)

        jf = ttk.Frame(add); jf.grid(row=r, column=0, columnspan=2, sticky="ew", padx=4, pady=2); r += 1
        ttk.Label(jf, text="Jog").pack(side="left")
        ttk.Combobox(jf, textvariable=self.jog_axis, values=["SM1", "SM2"], width=5, state="readonly").pack(side="left", padx=3)
        ttk.Combobox(jf, textvariable=self.jog_dir, values=["CW", "ACW"], width=5, state="readonly").pack(side="left", padx=3)
        ttk.Entry(jf, textvariable=self.jog_steps, width=7).pack(side="left", padx=3)
        ttk.Button(jf, text="Add Jog", command=self._add_jog).pack(side="left", padx=6)

        gf = ttk.Frame(add); gf.grid(row=r, column=0, columnspan=2, sticky="ew", padx=4, pady=2); r += 1
        ttk.Label(gf, text="SM1 → step").pack(side="left")
        ttk.Entry(gf, textvariable=self.goto_steps, width=8).pack(side="left", padx=4)
        ttk.Button(gf, text="Add Go-to-step", command=self._add_goto).pack(side="left", padx=6)

        # ---- sequence list (right) ----
        seq = ttk.LabelFrame(self, text="Sequence")
        seq.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        seq.rowconfigure(0, weight=1); seq.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(seq, height=12, activestyle="none")
        self.listbox.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(seq, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        self.listbox.configure(yscrollcommand=sb.set)
        edit = ttk.Frame(seq); edit.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 6))
        ttk.Button(edit, text="Up", command=lambda: self._move(-1)).pack(side="left", padx=2)
        ttk.Button(edit, text="Down", command=lambda: self._move(1)).pack(side="left", padx=2)
        ttk.Button(edit, text="Delete", command=self._delete).pack(side="left", padx=2)
        ttk.Button(edit, text="Clear", command=self._clear).pack(side="left", padx=2)
        ttk.Button(edit, text="Save…", command=self._save).pack(side="right", padx=2)
        ttk.Button(edit, text="Load…", command=self._load).pack(side="right", padx=2)

        # ---- run controls (bottom) ----
        run = ttk.LabelFrame(self, text="Run")
        run.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(run, text="Repeat (0 = loop):").pack(side="left", padx=(8, 2), pady=8)
        ttk.Entry(run, textvariable=self.repeat, width=5).pack(side="left")
        ttk.Button(run, text="Run", command=self._run_seq).pack(side="left", padx=(12, 4), pady=8)
        ttk.Button(run, text="Pause", command=self._pause).pack(side="left", padx=4)
        ttk.Button(run, text="Resume", command=self._resume).pack(side="left", padx=4)
        ttk.Button(run, text="Stop", command=self._stop).pack(side="left", padx=4)
        ttk.Button(run, text="ESTOP", command=lambda: self.app.send("ESTOP")).pack(side="left", padx=16)

        ttk.Label(self, textvariable=self.status, wraplength=760, justify="left",
                  font=("Segoe UI", 9, "bold")).grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 8))

    # ------------------------------------------------------- build steps

    def _int(self, var, name, minimum=None):
        raw = var.get().strip()
        try:
            v = int(raw)
        except ValueError:
            self.status.set("{} must be a whole number.".format(name))
            return None
        if minimum is not None and v < minimum:
            self.status.set("{} must be >= {}.".format(name, minimum))
            return None
        return v

    def _add(self, step):
        self.steps.append(step)
        self._refresh()

    def _add_cmd(self, label, cmd, timeout):
        self._add({"kind": "CMD", "label": label, "cmd": cmd, "timeout": timeout})

    def _add_wait(self):
        ms = self._int(self.wait_ms, "Wait", minimum=0)
        if ms is not None:
            self._add({"kind": "WAIT", "label": "Wait {} ms".format(ms), "ms": ms})

    def _add_jog(self):
        n = self._int(self.jog_steps, "Jog steps", minimum=1)
        if n is None:
            return
        axis, d = self.jog_axis.get(), self.jog_dir.get()
        self._add({"kind": "CMD", "label": "Jog {} {} {}".format(axis, d, n),
                   "cmd": "{} JOG {} {}".format(axis, d, n), "timeout": 60000})

    def _add_goto(self):
        n = self._int(self.goto_steps, "Step position", minimum=None)
        if n is not None:
            self._add({"kind": "CMD", "label": "SM1 → step {}".format(n),
                       "cmd": "SM1 GOTO STEPS {}".format(n), "timeout": 120000})

    def _refresh(self):
        self.listbox.delete(0, "end")
        for i, s in enumerate(self.steps):
            self.listbox.insert("end", "{:2d}.  {}".format(i + 1, s["label"]))

    def _selected(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    def _move(self, delta):
        i = self._selected()
        if i is None:
            return
        j = i + delta
        if 0 <= j < len(self.steps):
            self.steps[i], self.steps[j] = self.steps[j], self.steps[i]
            self._refresh()
            self.listbox.selection_set(j)

    def _delete(self):
        i = self._selected()
        if i is not None:
            del self.steps[i]
            self._refresh()

    def _clear(self):
        self.steps = []
        self._refresh()

    # -------------------------------------------------------- save / load

    def _save(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("Sequence", "*.json")], title="Save sequence")
        if not path:
            return
        try:
            with open(path, "w") as f:
                json.dump({"repeat": self.repeat.get(), "steps": self.steps}, f, indent=2)
            self.status.set("Saved: " + path)
        except Exception as exc:
            self.status.set("Save failed: {}".format(exc))

    def _load(self):
        path = filedialog.askopenfilename(filetypes=[("Sequence", "*.json")], title="Load sequence")
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
            self.steps = list(data.get("steps", []))
            self.repeat.set(str(data.get("repeat", "1")))
            self._refresh()
            self.status.set("Loaded: " + path)
        except Exception as exc:
            self.status.set("Load failed: {}".format(exc))

    # ------------------------------------------------------------ player

    def _highlight(self, idx):
        self.listbox.selection_clear(0, "end")
        if idx is not None and 0 <= idx < len(self.steps):
            self.listbox.selection_set(idx)
            self.listbox.see(idx)

    def _run_seq(self):
        if self._run:
            self.status.set("Already running - Stop first.")
            return
        if not self.steps:
            self.status.set("Sequence is empty.")
            return
        if not self.app.link.is_open():
            self.status.set("Not connected.")
            return
        rep = self._int(self.repeat, "Repeat", minimum=0)
        if rep is None:
            return
        self._loops_target = None if rep == 0 else rep
        self._loops_done = 0
        self._idx = 0
        self._run = True
        self._paused = False
        # make sure the firmware demo isn't holding the axes, and energize both
        self.app.send("DEMO PAUSE", log=False)
        self.app.send("SM1 ENABLE")
        self.app.send("SM2 ENABLE")
        self._exec_current()

    def _exec_current(self):
        if not self._run or self._paused:
            return
        if self._idx >= len(self.steps):                 # reached end of one pass
            self._loops_done += 1
            if self._loops_target is not None and self._loops_done >= self._loops_target:
                self._finish("Sequence complete ({} loop{}).".format(
                    self._loops_done, "" if self._loops_done == 1 else "s"))
                return
            self._idx = 0
        step = self.steps[self._idx]
        self._highlight(self._idx)
        loops = "∞" if self._loops_target is None else "{}/{}".format(self._loops_done + 1, self._loops_target)
        if step["kind"] == "WAIT":
            self.status.set("loop {} · step {}: {}".format(loops, self._idx + 1, step["label"]))
            self._wait_handle = self.app.root.after(step["ms"], self._step_done_ok)
        else:
            self.status.set("loop {} · step {}: {}".format(loops, self._idx + 1, step["label"]))
            self.app.send_expect(step["cmd"], self._step_result, timeout_ms=step["timeout"])

    def _step_result(self, ok, line):
        if not self._run:
            return
        if not ok:
            self._finish("STOPPED at step {} ({}): {}".format(self._idx + 1, self.steps[self._idx]["label"], line))
            return
        self._step_done_ok()

    def _step_done_ok(self):
        self._wait_handle = None
        if not self._run:
            return
        self._idx += 1
        if self._paused:
            self.status.set("Paused after step {} (Resume to continue).".format(self._idx))
            return
        self._exec_current()

    def _pause(self):
        if self._run and not self._paused:
            self._paused = True
            self.status.set("Pausing after the current step…")

    def _resume(self):
        if self._run and self._paused:
            self._paused = False
            self.status.set("Resuming…")
            self._exec_current()

    def _stop(self):
        if self._wait_handle is not None:
            try:
                self.app.root.after_cancel(self._wait_handle)
            except Exception:
                pass
            self._wait_handle = None
        self._run = False
        self._paused = False
        self._highlight(None)
        self.status.set("Stopped.")

    def _finish(self, msg):
        self._run = False
        self._paused = False
        self._highlight(None)
        self.status.set(msg)

"""Persistent JSON state on the Pico's flash filesystem.

This is what makes the demo resumable: every time the demo cycle changes
phase, moves the platform, or changes the gripper state, it calls
StateStore.save(). If the GUI issues DEMO PAUSE, or the Pico loses power and
reboots, or the USB cable is unplugged mid-cycle, the next boot (or the next
DEMO START/RESUME) picks up from the last saved phase/position/gripper
state instead of starting blind.

Writes are done to a temporary file and then renamed over the real one, so
a power loss mid-write cannot leave a half-written, unreadable state file.
"""

try:
    import ujson as json
except ImportError:
    import json

import os

try:
    import protocol
except ImportError:
    from firmware import protocol  # when unit-tested from the desktop side


class StateStore:
    def __init__(self, path=None):
        self.path = path or protocol.STATE_FILE_PATH
        self.tmp_path = self.path + ".tmp"
        self.data = {}

    def load(self, defaults):
        """Load saved state, falling back to `defaults` for any missing key."""
        loaded = {}
        try:
            with open(self.path, "r") as handle:
                loaded = json.load(handle)
        except (OSError, ValueError):
            loaded = {}

        merged = dict(defaults)
        merged.update(loaded)
        self.data = merged
        return self.data

    def save(self, data=None):
        if data is not None:
            self.data = data
        with open(self.tmp_path, "w") as handle:
            json.dump(self.data, handle)
        # os.rename() only overwrites an existing destination on POSIX-like
        # filesystems; some MicroPython VFS drivers (and every desktop
        # Windows test of this file) refuse instead. Clear the destination
        # first so this works either way.
        try:
            os.remove(self.path)
        except OSError:
            pass
        os.rename(self.tmp_path, self.path)

    def update(self, **fields):
        self.data.update(fields)
        self.save()

    def clear(self):
        self.data = {}
        try:
            os.remove(self.path)
        except OSError:
            pass

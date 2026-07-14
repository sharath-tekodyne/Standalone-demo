"""Timestamped Markdown session log, one file per GUI run."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


class SessionLogger:
    def __init__(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = LOG_DIR / f"session_{timestamp}.md"
        self.lines = []
        self._write_header()

    def _write_header(self):
        self.write("# Gripper Demo Session Report")
        self.write("")
        self.write(f"- Started: {datetime.now().isoformat(timespec='seconds')}")
        self.write("- Host: Windows GUI")
        self.write("")

    def write(self, line):
        self.lines.append(line)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def snapshot(self, title, fields):
        self.write(f"## {title}")
        for key, value in fields.items():
            self.write(f"- {key}: {value}")
        self.write("")

    def footer(self):
        self.write(f"- Updated: {datetime.now().isoformat(timespec='seconds')}")

    def export_text(self):
        return "\n".join(self.lines)

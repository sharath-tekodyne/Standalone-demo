"""Entry point for the rebuilt GUI:  python gui/run.py   (or  python -m gui.run)

Kept separate from the old desktop/ entry (gui_main.py) during the rebuild.
Once this GUI reaches parity, gui_main.py will point here.
"""

import os
import sys

# allow `python gui/run.py` from anywhere by putting the repo root on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk

from gui.app import App


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

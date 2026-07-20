"""Entry point for the desktop GUI: `python gui_main.py`.

The GUI now lives in the `gui/` package (rebuilt from scratch). This just
forwards to it so existing launchers/instructions keep working.
"""

from gui.run import main

if __name__ == "__main__":
    main()

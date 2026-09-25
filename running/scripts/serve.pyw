"""Windowless entry point for the GUI, with a system-tray icon.

pythonw.exe has no console, so stdout/stderr are None and any print() would
crash the app - both are redirected to data/gui.log before the server starts.

The Flask server runs on a daemon thread; the tray icon owns the main thread
so the process stays alive and can be quit from the tray menu.

    pythonw scripts/serve.pyw   ->  http://127.0.0.1:5001
"""

import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
sys.stdout = sys.stderr = open(BASE_DIR / "data" / "gui.log", "a",
                               buffering=1, encoding="utf-8")

from PIL import Image, ImageDraw  # noqa: E402
import pystray  # noqa: E402

from gui import app  # noqa: E402  (import after stdout is safe)

URL = "http://127.0.0.1:5001"


def make_icon():
    """A plain runner-orange disc - readable on light and dark taskbars."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=(226, 108, 46, 255))
    d.ellipse((18, 18, 46, 46), fill=(255, 255, 255, 255))
    return img


def open_claude_terminal():
    """Open a terminal at the running directory with Claude Code started.

    Windows Terminal (wt.exe) when installed, otherwise a plain cmd window.
    cmd /k keeps the window open once claude exits.
    """
    wt = shutil.which("wt.exe")
    if wt:
        cmd = [wt, "-d", str(BASE_DIR), "cmd", "/k", "claude"]
        flags = 0
    else:
        cmd = ["cmd", "/k", "claude"]
        flags = subprocess.CREATE_NEW_CONSOLE
    subprocess.Popen(cmd, cwd=str(BASE_DIR), creationflags=flags)


def main():
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=5001,
                               debug=False, use_reloader=False),
        daemon=True,
    ).start()
    print(f"Training plan GUI: {URL}")

    icon = pystray.Icon(
        "running",
        make_icon(),
        "Training plan - " + URL,
        menu=pystray.Menu(
            pystray.MenuItem("Open training plan", lambda: webbrowser.open(URL),
                             default=True),
            pystray.MenuItem("Open Claude terminal", lambda: open_claude_terminal()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda i: i.stop()),
        ),
    )
    icon.run()
    print("tray quit - shutting down")
    os._exit(0)  # the Flask thread has no clean stop hook


if __name__ == "__main__":
    main()

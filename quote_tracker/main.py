"""
Entry point for the HAWE Quote Tracker desktop app.

Creates the main window and starts the Tk event loop.  Drag-and-drop is enabled
when the optional ``tkinterdnd2`` package is available; otherwise the Browse
button is used (the app is fully functional either way).

The SQLite database is created next to the executable / script by default so it
can live in a shared OneDrive folder, exactly like the original tool.  Override
with the QUOTE_TRACKER_DB environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_dir() -> Path:
    """Folder the app 'lives' in (handles PyInstaller one-file builds)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _make_root():
    """Return (root, dnd_enabled). Prefer a DnD-capable root when available."""
    try:
        from tkinterdnd2 import TkinterDnD
        return TkinterDnD.Tk(), True
    except Exception:   # noqa: BLE001
        import tkinter as tk
        return tk.Tk(), False


def main() -> int:
    db_path = os.environ.get("QUOTE_TRACKER_DB") or str(_app_dir() / "hawe_quotes.db")

    try:
        import tkinter  # noqa: F401
    except Exception:   # noqa: BLE001
        sys.stderr.write(
            "Tkinter is not available in this Python installation.\n"
            "On Windows, reinstall Python from python.org (Tkinter is included "
            "by default).\n")
        return 1

    root, dnd = _make_root()

    # Import here so a missing display fails cleanly rather than at module load.
    from .gui import QuoteTrackerApp

    QuoteTrackerApp(root, db_path=db_path, dnd_enabled=dnd)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

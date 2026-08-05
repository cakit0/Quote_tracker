"""
Entry point for the HAWE Quote Tracker desktop app.

Creates the main window and starts the Tk event loop.  Drag-and-drop is enabled
when the optional ``tkinterdnd2`` package is available; otherwise the Browse
button is used (the app is fully functional either way).

The database location is resolved by ``config.get_db_path`` (env override → the
folder chosen in the app → a default next to the executable), so it can live in
a shared OneDrive folder, exactly like the original tool.
"""

from __future__ import annotations

import sys


def _make_root():
    """Return (root, dnd_enabled). Prefer a DnD-capable root when available."""
    try:
        from tkinterdnd2 import TkinterDnD
        return TkinterDnD.Tk(), True
    except Exception:   # noqa: BLE001
        import tkinter as tk
        return tk.Tk(), False


def main() -> int:
    from . import config
    db_path = config.get_db_path()

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

    app = QuoteTrackerApp(root, db_path=db_path, dnd_enabled=dnd)
    # Enforce the 6-month retention on the stored original files at startup.
    try:
        app.db.purge_old_originals()
        app.refresh_files()
    except Exception:   # noqa: BLE001
        pass
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

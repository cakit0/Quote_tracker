"""
Small persistent-settings helper.

Remembers where the user put the database between runs, so "Set Database
Folder…" sticks.  Settings live in a per-user config directory
(``%APPDATA%\\HAWEQuoteTracker`` on Windows) - never inside the app folder, so
they survive replacing the .exe.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "HAWEQuoteTracker"
DB_FILENAME = "hawe_quotes.db"


def config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _settings_path() -> Path:
    return config_dir() / "settings.json"


def load_settings() -> dict:
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    try:
        with open(_settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def default_db_dir() -> Path:
    """Where the database lives if the user has never chosen a folder.

    Next to the executable (frozen) or the project root (source) so it can sit
    in a shared OneDrive folder, matching the original tool's behaviour.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def get_db_path() -> str:
    """Resolve the database path: env override → saved setting → default."""
    env = os.environ.get("QUOTE_TRACKER_DB")
    if env:
        return env
    saved = load_settings().get("db_path")
    if saved:
        return saved
    return str(default_db_dir() / DB_FILENAME)


def set_db_path(path: str) -> None:
    data = load_settings()
    data["db_path"] = str(path)
    save_settings(data)

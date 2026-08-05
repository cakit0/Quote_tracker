"""
Central place for colours, fonts and ttk styling so the whole app has one
consistent look.  Colours match the HAWE brand used in the original tool.
"""

from __future__ import annotations

# ── HAWE brand palette ──────────────────────────────────────────────────────
RED      = "#E2001A"
RED_DARK = "#B00014"
DARK     = "#1A1A1A"
WHITE    = "#FFFFFF"
GRAY_BG  = "#F5F5F5"
GRAY_MID = "#E8E8E8"
BORDER   = "#D0D0D0"
TEXT     = "#2C2C2C"
MUTED    = "#6B6B6B"
ACCENT   = "#0066CC"
GREEN    = "#1A7A3C"
GREEN_BG = "#E8F5ED"
RED_BG   = "#FFF0F0"
DROP_BG  = "#FBECEC"

FONT        = ("Segoe UI", 10)
FONT_BOLD   = ("Segoe UI", 10, "bold")
FONT_SMALL  = ("Segoe UI", 9)
FONT_TITLE  = ("Segoe UI Semibold", 15)
FONT_KPI    = ("Segoe UI", 20, "bold")
FONT_DROP   = ("Segoe UI", 13)


def apply(root) -> None:
    """Apply ttk styling to the whole application."""
    from tkinter import ttk

    style = ttk.Style(root)
    try:
        style.theme_use("clam")   # 'clam' is themeable on every platform
    except Exception:             # noqa: BLE001
        pass

    style.configure(".", font=FONT, background=GRAY_BG, foreground=TEXT)
    style.configure("TFrame", background=GRAY_BG)
    style.configure("Card.TFrame", background=WHITE, relief="flat")
    style.configure("Header.TFrame", background=DARK)
    style.configure("TLabel", background=GRAY_BG, foreground=TEXT)
    style.configure("Card.TLabel", background=WHITE, foreground=TEXT)
    style.configure("Muted.TLabel", background=GRAY_BG, foreground=MUTED,
                    font=FONT_SMALL)
    style.configure("Title.TLabel", background=DARK, foreground=WHITE,
                    font=FONT_TITLE)
    style.configure("Sub.TLabel", background=DARK, foreground="#CFCFCF",
                    font=FONT_SMALL)
    style.configure("KpiValue.TLabel", background=WHITE, foreground=RED,
                    font=FONT_KPI)
    style.configure("KpiLabel.TLabel", background=WHITE, foreground=MUTED,
                    font=FONT_SMALL)

    # Buttons
    style.configure("TButton", padding=(12, 6), font=FONT_BOLD,
                    background=GRAY_MID, foreground=TEXT, borderwidth=0)
    style.map("TButton", background=[("active", BORDER)])
    style.configure("Accent.TButton", background=RED, foreground=WHITE)
    style.map("Accent.TButton",
              background=[("active", RED_DARK), ("pressed", RED_DARK)])
    style.configure("Ghost.TButton", background=WHITE, foreground=TEXT)
    style.map("Ghost.TButton", background=[("active", GRAY_MID)])

    # Notebook (tabs)
    style.configure("TNotebook", background=GRAY_BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(18, 9), font=FONT_BOLD,
                    background=GRAY_MID, foreground=MUTED)
    style.map("TNotebook.Tab",
              background=[("selected", WHITE)],
              foreground=[("selected", RED)])

    # Treeview (tables)
    style.configure("Treeview", background=WHITE, fieldbackground=WHITE,
                    foreground=TEXT, rowheight=26, borderwidth=0)
    style.configure("Treeview.Heading", font=FONT_BOLD, background=DARK,
                    foreground=WHITE, relief="flat", padding=(6, 6))
    style.map("Treeview.Heading", background=[("active", "#333333")])
    style.map("Treeview", background=[("selected", "#F7C9CE")],
              foreground=[("selected", DARK)])

    style.configure("TEntry", padding=5, fieldbackground=WHITE)
    style.configure("TCombobox", padding=4)

"""
Dialogs for correcting saved data and tidying the table.

* ``EditLineDialog``   - edit every field of a saved quote line, including its
  quantity price breaks, for when a quote was mis-read or a field was blank.
* ``ColumnChooser``    - show/hide individual table columns.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable, Dict, List, Optional, Sequence

from . import theme
from .parsers import parse_number

# (db field, label, width) for the simple text fields.
_FIELDS = [
    ("part_number", "Part #", 26),
    ("vendor", "Supplier", 26),
    ("quote_number", "Quote #", 26),
    ("description", "Description", 40),
    ("material", "Material", 26),
    ("lead_time", "Lead Time", 26),
    ("moq", "MOQ", 12),
    ("tooling", "Tooling", 12),
    ("currency", "Currency", 12),
]


class EditLineDialog(tk.Toplevel):
    """Edit one saved quote line and its price breaks."""

    def __init__(self, master, line: Dict, on_save: Callable[[Dict, Dict], None]):
        super().__init__(master)
        self.line = line
        self.on_save = on_save
        self._editor: Optional[tk.Entry] = None
        self.saved = False

        self.title(f"Edit line — {line.get('part_number') or ''}")
        self.configure(bg=theme.GRAY_BG)
        self.geometry("720x600")
        self.transient(master)
        self.grab_set()

        self._build_fields()
        self._build_breaks()
        self._build_buttons()

        self.bind("<Escape>", lambda e: self.destroy())

    # ── layout ──────────────────────────────────────────────────────────
    def _build_fields(self):
        head = ttk.Frame(self, padding=(16, 14, 16, 6))
        head.pack(fill="x")
        ttk.Label(head, text="Edit quote line", font=theme.FONT_TITLE).pack(anchor="w")
        ttk.Label(head, text="Correct anything that was mis-read or left blank.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        form = ttk.Frame(self, padding=(16, 6))
        form.pack(fill="x")
        self.vars: Dict[str, tk.StringVar] = {}
        for i, (key, label, width) in enumerate(_FIELDS):
            r, c = divmod(i, 2)
            cell = ttk.Frame(form)
            cell.grid(row=r, column=c, sticky="ew", padx=(0, 14), pady=4)
            form.columnconfigure(c, weight=1)
            ttk.Label(cell, text=label, style="Muted.TLabel").pack(anchor="w")
            val = self.line.get(key)
            var = tk.StringVar(value="" if val is None else
                               (f"{val:g}" if isinstance(val, float) else str(val)))
            self.vars[key] = var
            ttk.Entry(cell, textvariable=var, width=width).pack(fill="x")

        notes = ttk.Frame(self, padding=(16, 2))
        notes.pack(fill="x")
        ttk.Label(notes, text="Notes", style="Muted.TLabel").pack(anchor="w")
        self.notes_txt = tk.Text(notes, height=3, font=theme.FONT, bd=1,
                                 relief="solid", wrap="word")
        self.notes_txt.pack(fill="x")
        if self.line.get("notes"):
            self.notes_txt.insert("1.0", self.line["notes"])

    def _build_breaks(self):
        wrap = ttk.Frame(self, padding=(16, 8, 16, 4))
        wrap.pack(fill="both", expand=True)
        bar = ttk.Frame(wrap)
        bar.pack(fill="x")
        ttk.Label(bar, text="Quantity price breaks", style="Muted.TLabel").pack(side="left")
        ttk.Button(bar, text="Remove", style="Ghost.TButton",
                   command=self._remove_break).pack(side="right")
        ttk.Button(bar, text="+ Break", style="Ghost.TButton",
                   command=self._add_break).pack(side="right", padx=(0, 8))

        holder = ttk.Frame(wrap, style="Card.TFrame", padding=1)
        holder.pack(fill="both", expand=True, pady=(4, 0))
        self.tree = ttk.Treeview(holder, columns=("qty", "price"),
                                 show="headings", height=7)
        self.tree.heading("qty", text="Quantity")
        self.tree.heading("price", text="Unit Price")
        self.tree.column("qty", width=140, anchor="e")
        self.tree.column("price", width=140, anchor="e")
        vs = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._begin_edit)

        for qty, price in sorted((self.line.get("breaks") or {}).items()):
            self.tree.insert("", "end", values=(f"{qty:g}", f"{price:g}"))

        ttk.Label(wrap, text="Double-click a cell to edit it.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

    def _build_buttons(self):
        bar = ttk.Frame(self, padding=(16, 6, 16, 14))
        bar.pack(fill="x")
        ttk.Button(bar, text="Save changes", style="Accent.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(bar, text="Cancel", style="Ghost.TButton",
                   command=self.destroy).pack(side="right", padx=(0, 8))

    # ── break rows ──────────────────────────────────────────────────────
    def _add_break(self):
        iid = self.tree.insert("", "end", values=("", ""))
        self.tree.selection_set(iid)
        self.tree.see(iid)

    def _remove_break(self):
        sel = self.tree.selection()
        if sel:
            self.tree.delete(sel[0])

    def _begin_edit(self, event):
        if self._editor is not None:
            self._commit_edit()
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)
        iid = self.tree.identify_row(event.y)
        if not iid or not col:
            return
        key = self.tree["columns"][int(col[1:]) - 1]
        x, y, w, h = self.tree.bbox(iid, col)
        self._editor = tk.Entry(self.tree, font=theme.FONT, justify="right")
        self._editor.place(x=x, y=y, width=w, height=h)
        self._editor.insert(0, self.tree.set(iid, key))
        self._editor.focus_set()
        self._editor.select_range(0, "end")
        self._edit_target = (iid, key)
        self._editor.bind("<Return>", lambda e: self._commit_edit())
        self._editor.bind("<Escape>", lambda e: self._cancel_edit())
        self._editor.bind("<FocusOut>", lambda e: self._commit_edit())

    def _commit_edit(self):
        if self._editor is None:
            return
        iid, key = self._edit_target
        self.tree.set(iid, key, self._editor.get().strip())
        self._editor.destroy()
        self._editor = None

    def _cancel_edit(self):
        if self._editor is not None:
            self._editor.destroy()
            self._editor = None

    # ── save ────────────────────────────────────────────────────────────
    def _save(self):
        self._commit_edit()
        values: Dict = {}
        for key, _label, _w in _FIELDS:
            raw = self.vars[key].get().strip()
            if key in ("moq", "tooling"):
                values[key] = parse_number(raw)
            else:
                values[key] = raw
        values["notes"] = self.notes_txt.get("1.0", "end").strip()

        if not values["part_number"]:
            messagebox.showwarning("Part number required",
                                   "Enter a part number for this line.",
                                   parent=self)
            return

        breaks: Dict[float, float] = {}
        for iid in self.tree.get_children():
            qty = parse_number(self.tree.set(iid, "qty"))
            price = parse_number(self.tree.set(iid, "price"))
            if qty is None or price is None:
                continue
            if qty <= 0 or price <= 0:
                continue
            breaks[qty] = price

        self.saved = True
        self.on_save(values, breaks)
        self.destroy()


class ColumnChooser(tk.Toplevel):
    """Tick which columns a table shows.

    ``columns`` is a sequence of (key, label); ``hidden`` the currently hidden
    keys.  ``on_apply`` receives the new set of hidden keys.
    """

    def __init__(self, master, columns: Sequence, hidden: set,
                 on_apply: Callable[[set], None], title: str = "Columns"):
        super().__init__(master)
        self.on_apply = on_apply
        self.title(title)
        self.configure(bg=theme.GRAY_BG)
        self.transient(master)
        self.grab_set()
        self.resizable(False, True)

        ttk.Label(self, text="Show these columns", font=theme.FONT_BOLD,
                  padding=(14, 12, 14, 2)).pack(anchor="w")
        ttk.Label(self, text="Empty quantity columns are hidden automatically.",
                  style="Muted.TLabel", padding=(14, 0, 14, 8)).pack(anchor="w")

        canvas = tk.Canvas(self, bg=theme.WHITE, highlightthickness=0,
                           width=280, height=320)
        inner = ttk.Frame(canvas, style="Card.TFrame", padding=8)
        vs = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vs.set)
        canvas.pack(side="top", fill="both", expand=True, padx=14)
        vs.place(relx=1.0, rely=0.0, anchor="ne", relheight=1.0)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(win, width=e.width))

        self.vars: Dict[str, tk.BooleanVar] = {}
        for key, label in columns:
            var = tk.BooleanVar(value=key not in hidden)
            self.vars[key] = var
            ttk.Checkbutton(inner, text=label, variable=var).pack(anchor="w")

        bar = ttk.Frame(self, padding=(14, 10))
        bar.pack(fill="x")
        ttk.Button(bar, text="Apply", style="Accent.TButton",
                   command=self._apply).pack(side="right")
        ttk.Button(bar, text="Show all", style="Ghost.TButton",
                   command=self._show_all).pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())

    def _show_all(self):
        for var in self.vars.values():
            var.set(True)

    def _apply(self):
        hidden = {k for k, v in self.vars.items() if not v.get()}
        self.on_apply(hidden)
        self.destroy()

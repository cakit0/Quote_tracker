"""
The review dialog.

After a file is parsed we never save silently - we show the extracted rows in an
editable grid so the user can correct anything (essential for PDFs) before it
goes into the database.  Double-click a cell to edit it; use the buttons to add
or drop rows and quantity-break columns.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from typing import List, Optional

from . import theme
from .models import ParsedQuote, QuoteLine, PriceBreak
from .parsers import parse_number

_FIXED_COLS = [
    ("part_number", "Part #", 130),
    ("description", "Description", 200),
    ("material", "Material", 110),
    ("moq", "MOQ", 70),
    ("lead_time", "Lead Time", 90),
]


class ReviewDialog(tk.Toplevel):
    def __init__(self, master, quote: ParsedQuote, filename: str, on_save,
                 duplicate_check=None):
        super().__init__(master)
        self.quote = quote
        self.filename = filename
        self.on_save = on_save
        # Callable((part, vendor) pairs) -> dict of existing matches; lets the
        # dialog warn when this part was already quoted by this supplier.
        self.duplicate_check = duplicate_check
        self.result_saved = False

        # Mutable working copy of the quantity columns.
        self.quantities: List[float] = list(quote.quantities)
        self._editor: Optional[tk.Entry] = None

        self.title(f"Review quote - {filename}")
        self.configure(bg=theme.GRAY_BG)
        self.geometry("980x620")
        self.transient(master)
        self.grab_set()

        self._build_header()
        self._build_grid()
        self._build_buttons()
        self._load_rows()
        self._refresh_duplicates()

        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    # ── layout ──────────────────────────────────────────────────────────
    def _build_header(self):
        top = ttk.Frame(self, padding=(16, 14, 16, 8))
        top.pack(fill="x")

        ttk.Label(top, text="Review extracted quote", style="TLabel",
                  font=theme.FONT_TITLE).grid(row=0, column=0, columnspan=6,
                                              sticky="w")
        ttk.Label(top, text=f"{self.filename}  •  detected as "
                             f"{self.quote.source_type.upper()}  •  "
                             "double-click any cell to edit",
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=6,
                                             sticky="w", pady=(2, 10))

        ttk.Label(top, text="Vendor").grid(row=2, column=0, sticky="w")
        self.vendor_var = tk.StringVar(value=self.quote.vendor)
        ttk.Entry(top, textvariable=self.vendor_var, width=28).grid(
            row=2, column=1, sticky="w", padx=(6, 18))

        ttk.Label(top, text="Quote #").grid(row=2, column=2, sticky="w")
        self.quote_no_var = tk.StringVar(value=self.quote.quote_number)
        ttk.Entry(top, textvariable=self.quote_no_var, width=18).grid(
            row=2, column=3, sticky="w", padx=(6, 18))

        ttk.Label(top, text="Currency").grid(row=2, column=4, sticky="w")
        self.currency_var = tk.StringVar(value=self.quote.currency)
        ttk.Entry(top, textvariable=self.currency_var, width=8).grid(
            row=2, column=5, sticky="w", padx=(6, 0))

        ttk.Label(top, text="Project").grid(row=3, column=0, sticky="w",
                                            pady=(6, 0))
        self.project_var = tk.StringVar(value=self.quote.project)
        ttk.Entry(top, textvariable=self.project_var, width=28).grid(
            row=3, column=1, sticky="w", padx=(6, 18), pady=(6, 0))

        self.dup_lbl = ttk.Label(top, text="", style="Muted.TLabel",
                                 foreground=theme.RED, wraplength=900,
                                 justify="left")
        self.dup_lbl.grid(row=4, column=0, columnspan=6, sticky="w",
                          pady=(8, 0))

        if self.quote.warnings:
            warn = ttk.Label(
                top, text="⚠  " + "  |  ".join(self.quote.warnings),
                style="Muted.TLabel", foreground=theme.RED, wraplength=900,
                justify="left")
            warn.grid(row=5, column=0, columnspan=6, sticky="w", pady=(8, 0))

    def _column_ids(self):
        return ([c[0] for c in _FIXED_COLS] +
                [f"q{q:g}" for q in self.quantities])

    def _build_grid(self):
        wrap = ttk.Frame(self, style="Card.TFrame", padding=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=8)

        cols = self._column_ids()
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                 selectmode="browse")
        for key, label, width in _FIXED_COLS:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w", stretch=False)
        for q in self.quantities:
            cid = f"q{q:g}"
            self.tree.heading(cid, text=f"@{q:g}")
            self.tree.column(cid, width=80, anchor="e", stretch=False)

        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._begin_edit)

    def _build_buttons(self):
        bar = ttk.Frame(self, padding=(16, 4, 16, 14))
        bar.pack(fill="x")
        ttk.Button(bar, text="+ Row", style="Ghost.TButton",
                   command=self._add_row).pack(side="left")
        ttk.Button(bar, text="Remove row", style="Ghost.TButton",
                   command=self._remove_row).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="+ Quantity column", style="Ghost.TButton",
                   command=self._add_quantity).pack(side="left", padx=(8, 0))

        self.count_lbl = ttk.Label(bar, text="", style="Muted.TLabel")
        self.count_lbl.pack(side="left", padx=16)

        ttk.Button(bar, text="Save to database", style="Accent.TButton",
                   command=self._save).pack(side="right")
        ttk.Button(bar, text="Cancel", style="Ghost.TButton",
                   command=self._cancel).pack(side="right", padx=(0, 8))

    # ── data <-> grid ───────────────────────────────────────────────────
    def _line_to_values(self, ln: QuoteLine):
        vals = [
            ln.part_number,
            ln.description,
            ln.material,
            "" if ln.moq is None else f"{ln.moq:g}",
            ln.lead_time,
        ]
        for q in self.quantities:
            p = ln.price_at(q)
            vals.append("" if p is None else f"{p:g}")
        return vals

    def _refresh_duplicates(self) -> dict:
        """Flag rows whose part + supplier are already in the database."""
        if self.duplicate_check is None:
            return {}
        vendor = self.vendor_var.get().strip()
        pairs = []
        for iid in self.tree.get_children():
            part = str(self.tree.set(iid, "part_number")).strip()
            if part:
                pairs.append((part, vendor))
        if not pairs:
            self.dup_lbl.config(text="")
            return {}
        try:
            dups = self.duplicate_check(pairs) or {}
        except Exception:   # noqa: BLE001 - a flag is never worth failing over
            return {}
        if dups:
            parts = sorted({d["part_number"] for d in dups.values()})
            shown = ", ".join(parts[:4]) + ("…" if len(parts) > 4 else "")
            self.dup_lbl.config(
                text=f"⚠  Already in the database from {vendor or 'this supplier'}: "
                     f"{shown}. Saving adds another quote for the same part — "
                     f"fine for a re-quote, but check you're not loading a duplicate.")
        else:
            self.dup_lbl.config(text="")
        return dups

    def _load_rows(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for ln in self.quote.lines:
            self.tree.insert("", "end", values=self._line_to_values(ln))
        self._update_count()

    def _update_count(self):
        n = len(self.tree.get_children())
        self.count_lbl.config(text=f"{n} line(s)  •  "
                                   f"{len(self.quantities)} quantity break(s)")

    def _add_row(self):
        blank = [""] * len(self._column_ids())
        iid = self.tree.insert("", "end", values=blank)
        self.tree.selection_set(iid)
        self.tree.see(iid)
        self._update_count()

    def _remove_row(self):
        sel = self.tree.selection()
        if sel:
            self.tree.delete(sel[0])
            self._update_count()

    def _add_quantity(self):
        val = simpledialog.askstring("Add quantity break",
                                     "Quantity (e.g. 250):", parent=self)
        q = parse_number(val)
        if q is None or q <= 0:
            if val is not None:
                messagebox.showwarning("Invalid", "Enter a positive number.",
                                       parent=self)
            return
        if q in self.quantities:
            return
        # Preserve current edits, add the column, rebuild.
        self.quote = self._collect(validate=False)
        self.quantities = sorted(set(self.quantities) | {q})
        for child in self.tree.master.winfo_children():
            child.destroy()
        self._build_grid()
        self._load_rows()

    # ── in-place cell editing ───────────────────────────────────────────
    def _begin_edit(self, event):
        if self._editor is not None:
            self._commit_edit()
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        col = self.tree.identify_column(event.x)   # like "#3"
        iid = self.tree.identify_row(event.y)
        if not iid or not col:
            return
        col_index = int(col[1:]) - 1
        x, y, w, h = self.tree.bbox(iid, col)
        cur = self.tree.set(iid, self.tree["columns"][col_index])

        self._editor = tk.Entry(self.tree, font=theme.FONT)
        self._editor.place(x=x, y=y, width=w, height=h)
        self._editor.insert(0, cur)
        self._editor.focus_set()
        self._editor.select_range(0, "end")
        self._edit_target = (iid, self.tree["columns"][col_index])
        self._editor.bind("<Return>", lambda e: self._commit_edit())
        self._editor.bind("<Escape>", lambda e: self._cancel_edit())
        self._editor.bind("<FocusOut>", lambda e: self._commit_edit())

    def _commit_edit(self):
        if self._editor is None:
            return
        iid, col = self._edit_target
        self.tree.set(iid, col, self._editor.get().strip())
        self._editor.destroy()
        self._editor = None

    def _cancel_edit(self):
        if self._editor is not None:
            self._editor.destroy()
            self._editor = None

    # ── collect + save ──────────────────────────────────────────────────
    def _collect(self, validate: bool = True) -> ParsedQuote:
        if self._editor is not None:
            self._commit_edit()
        cols = self._column_ids()
        lines: List[QuoteLine] = []
        for iid in self.tree.get_children():
            row = self.tree.item(iid, "values")
            data = dict(zip(cols, row))
            part = (data.get("part_number") or "").strip()
            desc = (data.get("description") or "").strip()
            if not part and not desc:
                continue
            breaks = []
            for q in self.quantities:
                price = parse_number(data.get(f"q{q:g}"))
                if price is not None and price > 0:
                    breaks.append(PriceBreak(quantity=q, unit_price=price))
            lines.append(QuoteLine(
                part_number=part or desc,
                description=desc,
                material=(data.get("material") or "").strip(),
                moq=parse_number(data.get("moq")),
                lead_time=(data.get("lead_time") or "").strip(),
                vendor=self.vendor_var.get().strip(),
                quote_number=self.quote_no_var.get().strip(),
                breaks=breaks,
            ))
        return ParsedQuote(
            source_type=self.quote.source_type,
            vendor=self.vendor_var.get().strip(),
            quote_number=self.quote_no_var.get().strip(),
            project=self.project_var.get().strip(),
            currency=self.currency_var.get().strip(),
            lines=lines,
            warnings=self.quote.warnings,
        )

    def _save(self):
        quote = self._collect()
        if not quote.lines:
            messagebox.showwarning(
                "Nothing to save",
                "There are no lines with a part number and at least one price.",
                parent=self)
            return
        priced = sum(1 for ln in quote.lines if ln.breaks)
        if priced == 0:
            if not messagebox.askyesno(
                    "No prices",
                    "None of the lines have a price break. Save anyway?",
                    parent=self):
                return
        dups = self._refresh_duplicates()
        if dups:
            parts = sorted({d["part_number"] for d in dups.values()})
            if not messagebox.askyesno(
                    "Already quoted",
                    f"{', '.join(parts[:6])}\n\nalready exist(s) in the database "
                    f"from {quote.vendor or 'this supplier'}.\n\n"
                    "Save this quote as well? (Yes keeps both, so you can "
                    "compare the old and new price.)",
                    parent=self):
                return

        self.result_saved = True
        self.on_save(quote)
        self.destroy()

    def _cancel(self):
        self._cancel_edit()
        self.destroy()

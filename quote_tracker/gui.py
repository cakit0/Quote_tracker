"""
Main application window.

A single native window (no browser, no local web server) with four tabs:
Import, Quote Log, Comparison and Files.  Drag files onto the Import tab - or
use the Browse button - to extract quotes; everything passes through the review
dialog before being stored.
"""

from __future__ import annotations

import os
import tkinter as tk
from datetime import datetime
from tkinter import ttk, filedialog, messagebox
from typing import List

from . import theme
from .database import QuoteDB
from .parsers import parse_file, SUPPORTED_EXTENSIONS
from .review_dialog import ReviewDialog

APP_TITLE = "HAWE Quote Tracker"
APP_SUBTITLE = "Supplier price tracker — drag a PDF, Excel or CSV quote to begin"


class QuoteTrackerApp:
    def __init__(self, root: tk.Tk, db_path: str, dnd_enabled: bool = False):
        self.root = root
        self.db = QuoteDB(db_path)
        self.db_path = db_path
        self.dnd_enabled = dnd_enabled

        self.root.title(APP_TITLE)
        self.root.geometry("1180x760")
        self.root.minsize(940, 600)
        self.root.configure(bg=theme.GRAY_BG)
        theme.apply(self.root)

        self._build_header()
        self._build_kpis()
        self._build_tabs()
        self.refresh_all()

    # ── header + KPIs ───────────────────────────────────────────────────
    def _build_header(self):
        head = tk.Frame(self.root, bg=theme.DARK)
        head.pack(fill="x")
        inner = tk.Frame(head, bg=theme.DARK)
        inner.pack(fill="x", padx=22, pady=14)

        bar = tk.Frame(inner, bg=theme.RED, width=6, height=44)
        bar.pack(side="left", padx=(0, 14))
        bar.pack_propagate(False)

        txt = tk.Frame(inner, bg=theme.DARK)
        txt.pack(side="left")
        tk.Label(txt, text=APP_TITLE, bg=theme.DARK, fg=theme.WHITE,
                 font=theme.FONT_TITLE).pack(anchor="w")
        tk.Label(txt, text=APP_SUBTITLE, bg=theme.DARK, fg="#CFCFCF",
                 font=theme.FONT_SMALL).pack(anchor="w")

        self.db_lbl = tk.Label(inner, text="", bg=theme.DARK, fg="#8A8A8A",
                               font=theme.FONT_SMALL, justify="right")
        self.db_lbl.pack(side="right")

    def _build_kpis(self):
        self.kpi_frame = tk.Frame(self.root, bg=theme.GRAY_BG)
        self.kpi_frame.pack(fill="x", padx=18, pady=(14, 4))
        self.kpi_cards = {}
        specs = [
            ("parts", "Parts / drawings", theme.RED),
            ("vendors", "Suppliers", theme.DARK),
            ("lines", "Quote lines", theme.ACCENT),
            ("files", "Files loaded", theme.MUTED),
            ("best_price", "Lowest unit price", theme.GREEN),
        ]
        for i, (key, label, color) in enumerate(specs):
            card = tk.Frame(self.kpi_frame, bg=theme.WHITE,
                            highlightbackground=theme.BORDER,
                            highlightthickness=1)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))
            self.kpi_frame.columnconfigure(i, weight=1)
            accent = tk.Frame(card, bg=color, height=4)
            accent.pack(fill="x")
            val = tk.Label(card, text="—", bg=theme.WHITE, fg=color,
                           font=theme.FONT_KPI)
            val.pack(anchor="w", padx=14, pady=(10, 0))
            tk.Label(card, text=label, bg=theme.WHITE, fg=theme.MUTED,
                     font=theme.FONT_SMALL).pack(anchor="w", padx=14, pady=(0, 12))
            self.kpi_cards[key] = val

    # ── tabs ────────────────────────────────────────────────────────────
    def _build_tabs(self):
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=18, pady=(8, 16))
        self._build_import_tab()
        self._build_log_tab()
        self._build_compare_tab()
        self._build_files_tab()

    def _build_import_tab(self):
        tab = ttk.Frame(self.nb, padding=18)
        self.nb.add(tab, text="  Import  ")

        drop = tk.Frame(tab, bg=theme.DROP_BG, highlightbackground=theme.RED,
                        highlightthickness=2, bd=0)
        drop.pack(fill="both", expand=False, ipady=30, pady=(4, 14))
        hint = ("Drag PDF / Excel / CSV files here"
                if self.dnd_enabled else
                "Click ‘Browse files…’ to add a quote")
        tk.Label(drop, text="⬇", bg=theme.DROP_BG, fg=theme.RED,
                 font=("Segoe UI", 34, "bold")).pack(pady=(10, 4))
        tk.Label(drop, text=hint, bg=theme.DROP_BG, fg=theme.DARK,
                 font=theme.FONT_DROP).pack()
        tk.Label(drop, text="Supported: .pdf  .xlsx  .csv  .tsv  .txt",
                 bg=theme.DROP_BG, fg=theme.MUTED,
                 font=theme.FONT_SMALL).pack(pady=(4, 8))
        ttk.Button(drop, text="Browse files…", style="Accent.TButton",
                   command=self._browse).pack(pady=(2, 12))

        if self.dnd_enabled:
            self._register_dnd(drop)

        ttk.Label(tab, text="Activity", style="Muted.TLabel").pack(anchor="w")
        log_wrap = ttk.Frame(tab, style="Card.TFrame", padding=1)
        log_wrap.pack(fill="both", expand=True, pady=(4, 0))
        self.activity = tk.Text(log_wrap, height=8, font=theme.FONT_SMALL,
                                bg=theme.WHITE, fg=theme.TEXT, bd=0,
                                relief="flat", wrap="word", state="disabled")
        self.activity.pack(fill="both", expand=True, padx=8, pady=8)
        self._log("Ready. Add a supplier quote to get started.")

    def _build_log_tab(self):
        tab = ttk.Frame(self.nb, padding=(18, 14))
        self.nb.add(tab, text="  Quote Log  ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="Search").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh_log())
        ttk.Entry(bar, textvariable=self.search_var, width=26).pack(
            side="left", padx=(6, 16))
        ttk.Label(bar, text="Supplier").pack(side="left")
        self.vendor_var = tk.StringVar(value="(all)")
        self.vendor_cb = ttk.Combobox(bar, textvariable=self.vendor_var,
                                      width=22, state="readonly")
        self.vendor_cb.pack(side="left", padx=(6, 0))
        self.vendor_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_log())

        ttk.Button(bar, text="Export to Excel", style="Ghost.TButton",
                   command=self._export_excel).pack(side="right")
        ttk.Button(bar, text="Delete line", style="Ghost.TButton",
                   command=self._delete_line).pack(side="right", padx=(0, 8))

        self.log_wrap = ttk.Frame(tab, style="Card.TFrame", padding=1)
        self.log_wrap.pack(fill="both", expand=True)
        self.log_tree = None   # built dynamically per quantity set

    def _build_compare_tab(self):
        tab = ttk.Frame(self.nb, padding=(18, 14))
        self.nb.add(tab, text="  Comparison  ")
        ttk.Label(tab, text="Best (lowest) unit price per part at each quantity, "
                            "with the winning supplier.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        self.cmp_wrap = ttk.Frame(tab, style="Card.TFrame", padding=1)
        self.cmp_wrap.pack(fill="both", expand=True)
        self.cmp_tree = None

    def _build_files_tab(self):
        tab = ttk.Frame(self.nb, padding=(18, 14))
        self.nb.add(tab, text="  Files  ")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Button(bar, text="Remove selected file", style="Ghost.TButton",
                   command=self._delete_file).pack(side="right")

        wrap = ttk.Frame(tab, style="Card.TFrame", padding=1)
        wrap.pack(fill="both", expand=True)
        cols = ("filename", "type", "vendor", "lines", "loaded")
        self.files_tree = ttk.Treeview(wrap, columns=cols, show="headings")
        for c, label, w in [("filename", "File", 340), ("type", "Type", 70),
                            ("vendor", "Supplier", 200), ("lines", "Lines", 70),
                            ("loaded", "Loaded", 160)]:
            self.files_tree.heading(c, text=label)
            self.files_tree.column(c, width=w,
                                   anchor="e" if c == "lines" else "w")
        vs = ttk.Scrollbar(wrap, orient="vertical",
                           command=self.files_tree.yview)
        self.files_tree.configure(yscrollcommand=vs.set)
        self.files_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

    # ── drag & drop ─────────────────────────────────────────────────────
    def _register_dnd(self, widget):
        try:
            from tkinterdnd2 import DND_FILES
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:   # noqa: BLE001
            self.dnd_enabled = False

    def _on_drop(self, event):
        paths = self._split_dnd_paths(event.data)
        self._handle_files(paths)

    @staticmethod
    def _split_dnd_paths(data: str) -> List[str]:
        # tkdnd wraps paths containing spaces in {curly braces}.
        paths, buf, brace = [], "", False
        for ch in data:
            if ch == "{":
                brace = True
            elif ch == "}":
                brace = False
                paths.append(buf); buf = ""
            elif ch == " " and not brace:
                if buf:
                    paths.append(buf); buf = ""
            else:
                buf += ch
        if buf:
            paths.append(buf)
        return [p for p in paths if p]

    # ── file handling ───────────────────────────────────────────────────
    def _browse(self):
        paths = filedialog.askopenfilenames(
            title="Select supplier quote(s)",
            filetypes=[("Quote files", "*.pdf *.xlsx *.xlsm *.csv *.tsv *.txt"),
                       ("PDF", "*.pdf"), ("Excel", "*.xlsx *.xlsm"),
                       ("CSV / text", "*.csv *.tsv *.txt"),
                       ("All files", "*.*")])
        if paths:
            self._handle_files(list(paths))

    def _handle_files(self, paths: List[str]):
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            name = os.path.basename(path)
            if ext not in SUPPORTED_EXTENSIONS:
                self._log(f"✗ Skipped {name}: unsupported type ({ext}).")
                continue
            try:
                fhash = QuoteDB.file_hash(path)
            except OSError as exc:
                self._log(f"✗ Could not read {name}: {exc}")
                continue
            dup = self.db.find_by_hash(fhash)
            if dup:
                self._log(f"• {name} already loaded as “{dup['filename']}”. Skipped.")
                continue
            try:
                quote = parse_file(path)
            except Exception as exc:   # noqa: BLE001
                self._log(f"✗ Failed to parse {name}: {exc}")
                messagebox.showerror("Parse error",
                                     f"Could not parse {name}:\n{exc}")
                continue
            self._log(f"→ {name}: extracted {len(quote.lines)} line(s). "
                      "Opening review…")
            self._open_review(quote, name, fhash)

    def _open_review(self, quote, name, fhash):
        def on_save(edited):
            file_id = self.db.save_quote(edited, name, fhash)
            self._log(f"✓ Saved {name}: {len(edited.lines)} line(s) "
                      f"(supplier: {edited.vendor or 'n/a'}).")
            self.refresh_all()
        ReviewDialog(self.root, quote, name, on_save)

    # ── refresh ─────────────────────────────────────────────────────────
    def refresh_all(self):
        self._refresh_kpis()
        self._refresh_vendors()
        self.refresh_log()
        self.refresh_compare()
        self.refresh_files()
        size = (os.path.getsize(self.db_path) / 1024
                if os.path.exists(self.db_path) else 0)
        self.db_lbl.config(text=f"Database:\n{self.db_path}\n{size:,.0f} KB")

    def _refresh_kpis(self):
        k = self.db.kpis()
        self.kpi_cards["parts"].config(text=str(k["parts"]))
        self.kpi_cards["vendors"].config(text=str(k["vendors"]))
        self.kpi_cards["lines"].config(text=str(k["lines"]))
        self.kpi_cards["files"].config(text=str(k["files"]))
        bp = k["best_price"]
        self.kpi_cards["best_price"].config(
            text="—" if bp is None else f"{bp:,.2f}")

    def _refresh_vendors(self):
        vendors = ["(all)"] + self.db.vendors()
        self.vendor_cb["values"] = vendors
        if self.vendor_var.get() not in vendors:
            self.vendor_var.set("(all)")

    def refresh_log(self):
        quantities = self.db.distinct_quantities()
        search = self.search_var.get().strip()
        vendor = self.vendor_var.get()
        vendor = "" if vendor == "(all)" else vendor
        rows = self.db.quote_log(search=search, vendor=vendor)

        base = [("part_number", "Part #", 130), ("vendor", "Supplier", 150),
                ("description", "Description", 190), ("material", "Material", 100)]
        qcols = [(f"q{q:g}", f"@{q:g}", 80) for q in quantities]
        self.log_tree = self._rebuild_tree(self.log_wrap, self.log_tree,
                                           base + qcols,
                                           right_align={c[0] for c in qcols})
        for r in rows:
            vals = [r["part_number"], r["vendor"] or "", r["description"] or "",
                    r["material"] or ""]
            for q in quantities:
                p = r["breaks"].get(q)
                vals.append("" if p is None else f"{p:,.2f}")
            self.log_tree.insert("", "end", iid=str(r["id"]), values=vals)

    def refresh_compare(self):
        quantities = self.db.distinct_quantities()
        data = self.db.comparison()
        base = [("part_number", "Part #", 130), ("description", "Description", 200),
                ("suppliers", "# Suppliers", 90)]
        qcols = [(f"q{q:g}", f"Best @{q:g}", 160) for q in quantities]
        self.cmp_tree = self._rebuild_tree(self.cmp_wrap, self.cmp_tree,
                                           base + qcols,
                                           right_align={c[0] for c in qcols})
        for g in data:
            vals = [g["part_number"], g["description"], len(g["vendors"])]
            for q in quantities:
                if q in g["best"]:
                    price, vendor = g["best"][q]
                    vals.append(f"{price:,.2f}  ({vendor or '?'})")
                else:
                    vals.append("")
            self.cmp_tree.insert("", "end", values=vals)

    def refresh_files(self):
        for iid in self.files_tree.get_children():
            self.files_tree.delete(iid)
        for f in self.db.list_files():
            self.files_tree.insert(
                "", "end", iid=str(f["id"]),
                values=(f["filename"], (f["source_type"] or "").upper(),
                        f["vendor"] or "", f["line_count"],
                        f["loaded_at"] or ""))

    def _rebuild_tree(self, parent, existing, columns, right_align=None):
        right_align = right_align or set()
        if existing is not None:
            existing.master.destroy()
        holder = ttk.Frame(parent, style="Card.TFrame")
        holder.pack(fill="both", expand=True)
        ids = [c[0] for c in columns]
        tree = ttk.Treeview(holder, columns=ids, show="headings")
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, stretch=False,
                        anchor="e" if key in right_align else "w")
        vs = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        hs = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        return tree

    # ── actions ─────────────────────────────────────────────────────────
    def _delete_line(self):
        if not self.log_tree:
            return
        sel = self.log_tree.selection()
        if not sel:
            messagebox.showinfo("Delete line", "Select a line first.")
            return
        if messagebox.askyesno("Delete line", "Delete the selected quote line?"):
            self.db.delete_line(int(sel[0]))
            self.refresh_all()

    def _delete_file(self):
        sel = self.files_tree.selection()
        if not sel:
            messagebox.showinfo("Remove file", "Select a file first.")
            return
        if messagebox.askyesno("Remove file",
                               "Remove this file and all its quote lines?"):
            self.db.delete_file(int(sel[0]))
            self.refresh_all()

    def _export_excel(self):
        rows = self.db.export_rows()
        if not rows:
            messagebox.showinfo("Export", "There is nothing to export yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialfile=f"Quote_Export_{datetime.now():%Y%m%d_%H%M}.xlsx",
            filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            self._write_excel(path, rows)
        except Exception as exc:   # noqa: BLE001
            messagebox.showerror("Export failed", str(exc))
            return
        self._log(f"✓ Exported {len(rows)} line(s) to {os.path.basename(path)}.")
        messagebox.showinfo("Export complete", f"Saved:\n{path}")

    def _write_excel(self, path, rows):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        quantities = self.db.distinct_quantities()
        wb = Workbook()
        ws = wb.active
        ws.title = "Quote Log"
        headers = (["Part #", "Supplier", "Description", "Material", "MOQ",
                    "Lead Time", "Currency"] + [f"@{q:g}" for q in quantities] +
                   ["Notes", "File"])
        ws.append(headers)
        hf = Font(color="FFFFFF", bold=True)
        fill = PatternFill("solid", fgColor="1A1A1A")
        for cell in ws[1]:
            cell.font = hf
            cell.fill = fill
        for r in rows:
            row = [r["part_number"], r["vendor"], r["description"], r["material"],
                   r["moq"], r["lead_time"], r["currency"]]
            row += [r["breaks"].get(q) for q in quantities]
            row += [r["notes"], r["filename"]]
            ws.append(row)
        ws.freeze_panes = "A2"

        cmp_ws = wb.create_sheet("Best Price")
        cmp_ws.append(["Part #", "Description", "# Suppliers"] +
                      [f"Best @{q:g}" for q in quantities] + ["Winning supplier(s)"])
        for cell in cmp_ws[1]:
            cell.font = hf
            cell.fill = fill
        for g in self.db.comparison():
            line = [g["part_number"], g["description"], len(g["vendors"])]
            winners = set()
            for q in quantities:
                if q in g["best"]:
                    price, vendor = g["best"][q]
                    line.append(price)
                    if vendor:
                        winners.add(vendor)
                else:
                    line.append(None)
            line.append(", ".join(sorted(winners)))
            cmp_ws.append(line)
        wb.save(path)

    # ── activity log ────────────────────────────────────────────────────
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M")
        self.activity.config(state="normal")
        self.activity.insert("1.0", f"[{ts}]  {msg}\n")
        self.activity.config(state="disabled")

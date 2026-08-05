"""
Main application window.

A single native window (no browser, no local web server) with five tabs:
Import, Quote Log, Study, Files and (via the menu bar) database tools.

- Import   : drag / browse PDF, Excel or CSV quotes -> review -> save.
- Quote Log: every quote line, filterable by part number, supplier and text.
- Study    : per-part supplier comparison (price + delivery) like the overview
             sheet, with the best price at each quantity and the fastest
             delivery flagged so tradeoffs are obvious.
- Files    : loaded files; download / open the original quote; remove files.
- Database menu: choose the database folder, back it up, purge old originals.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tkinter as tk
from datetime import datetime
from tkinter import ttk, filedialog, messagebox
from typing import List

from . import theme, config
from .database import QuoteDB, ORIGINAL_RETENTION_DAYS
from .parsers import parse_file, SUPPORTED_EXTENSIONS
from .review_dialog import ReviewDialog

APP_TITLE = "HAWE Quote Tracker"
APP_SUBTITLE = "Supplier price tracker — drag a PDF, Excel or CSV quote to begin"
BEST = "★ "   # marker prefixed to a best price / fastest delivery cell


def open_path(path: str) -> None:
    """Open a file or folder with the OS default handler."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)                                    # noqa: SLF001
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception as exc:   # noqa: BLE001
        messagebox.showerror("Could not open", str(exc))


class QuoteTrackerApp:
    def __init__(self, root: tk.Tk, db_path: str, dnd_enabled: bool = False):
        self.root = root
        self.db = QuoteDB(db_path)
        self.db_path = db_path
        self.dnd_enabled = dnd_enabled

        self.root.title(APP_TITLE)
        self.root.geometry("1200x780")
        self.root.minsize(960, 620)
        self.root.configure(bg=theme.GRAY_BG)
        theme.apply(self.root)

        self._build_menu()
        self._build_header()
        self._build_kpis()
        self._build_tabs()
        self.refresh_all()

    # ── menu bar ────────────────────────────────────────────────────────
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        dbmenu = tk.Menu(menubar, tearoff=0)
        dbmenu.add_command(label="Set database folder…",
                           command=self._set_db_folder)
        dbmenu.add_command(label="Back up database now…",
                           command=self._backup_db)
        dbmenu.add_command(label="Open database folder",
                           command=lambda: open_path(os.path.dirname(
                               os.path.abspath(self.db_path))))
        dbmenu.add_separator()
        dbmenu.add_command(
            label=f"Purge originals older than 6 months",
            command=self._purge_now)
        menubar.add_cascade(label="Database", menu=dbmenu)

        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(label="About / How it works", command=self._about)
        menubar.add_cascade(label="Help", menu=helpmenu)

        self.root.config(menu=menubar)

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
            tk.Frame(card, bg=color, height=4).pack(fill="x")
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
        self._build_study_tab()
        self._build_files_tab()

    def _build_import_tab(self):
        tab = ttk.Frame(self.nb, padding=18)
        self.nb.add(tab, text="  Import  ")

        drop = tk.Frame(tab, bg=theme.DROP_BG, highlightbackground=theme.RED,
                        highlightthickness=2, bd=0)
        drop.pack(fill="both", expand=False, ipady=30, pady=(4, 14))
        hint = ("Drag PDF / Excel / CSV files here"
                if self.dnd_enabled else "Click ‘Browse files…’ to add a quote")
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
        ttk.Entry(bar, textvariable=self.search_var, width=22).pack(
            side="left", padx=(6, 14))

        ttk.Label(bar, text="Part #").pack(side="left")
        self.log_part_var = tk.StringVar(value="(all)")
        self.log_part_cb = ttk.Combobox(bar, textvariable=self.log_part_var,
                                        width=18, state="readonly")
        self.log_part_cb.pack(side="left", padx=(6, 14))
        self.log_part_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_log())

        ttk.Label(bar, text="Supplier").pack(side="left")
        self.vendor_var = tk.StringVar(value="(all)")
        self.vendor_cb = ttk.Combobox(bar, textvariable=self.vendor_var,
                                      width=18, state="readonly")
        self.vendor_cb.pack(side="left", padx=(6, 0))
        self.vendor_cb.bind("<<ComboboxSelected>>", lambda e: self.refresh_log())

        ttk.Button(bar, text="Export to Excel", style="Ghost.TButton",
                   command=self._export_excel).pack(side="right")
        ttk.Button(bar, text="Delete line", style="Ghost.TButton",
                   command=self._delete_line).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="Clear filters", style="Ghost.TButton",
                   command=self._clear_log_filters).pack(side="right", padx=(0, 8))

        self.log_wrap = ttk.Frame(tab, style="Card.TFrame", padding=1)
        self.log_wrap.pack(fill="both", expand=True)
        self.log_tree = None

    def _build_study_tab(self):
        tab = ttk.Frame(self.nb, padding=(18, 14))
        self.nb.add(tab, text="  Study  ")

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Part #").pack(side="left")
        self.study_part_var = tk.StringVar(value="(all)")
        self.study_part_cb = ttk.Combobox(bar, textvariable=self.study_part_var,
                                          width=18, state="readonly")
        self.study_part_cb.pack(side="left", padx=(6, 14))
        self.study_part_cb.bind("<<ComboboxSelected>>",
                                lambda e: self.refresh_study())

        ttk.Label(bar, text="Supplier").pack(side="left")
        self.study_vendor_var = tk.StringVar(value="(all)")
        self.study_vendor_cb = ttk.Combobox(bar, textvariable=self.study_vendor_var,
                                            width=18, state="readonly")
        self.study_vendor_cb.pack(side="left", padx=(6, 14))
        self.study_vendor_cb.bind("<<ComboboxSelected>>",
                                  lambda e: self.refresh_study())

        ttk.Button(bar, text="Collapse all", style="Ghost.TButton",
                   command=lambda: self._expand_study(False)).pack(side="right")
        ttk.Button(bar, text="Expand all", style="Ghost.TButton",
                   command=lambda: self._expand_study(True)).pack(
                       side="right", padx=(0, 8))

        ttk.Label(tab, text="Each part lists every supplier.  ★ marks the lowest "
                            "price at that quantity and the fastest delivery — "
                            "so you can weigh price against lead time.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))

        self.study_wrap = ttk.Frame(tab, style="Card.TFrame", padding=1)
        self.study_wrap.pack(fill="both", expand=True)
        self.study_tree = None

    def _build_files_tab(self):
        tab = ttk.Frame(self.nb, padding=(18, 14))
        self.nb.add(tab, text="  Files  ")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text=f"Original files are kept for re-download and "
                            f"auto-removed after 6 months.",
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(bar, text="Remove file", style="Ghost.TButton",
                   command=self._delete_file).pack(side="right")
        ttk.Button(bar, text="Open original", style="Ghost.TButton",
                   command=self._open_original).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="Download original", style="Accent.TButton",
                   command=self._download_original).pack(side="right", padx=(0, 8))

        wrap = ttk.Frame(tab, style="Card.TFrame", padding=1)
        wrap.pack(fill="both", expand=True)
        cols = ("filename", "type", "vendor", "lines", "loaded", "original")
        self.files_tree = ttk.Treeview(wrap, columns=cols, show="headings")
        for c, label, w in [("filename", "File", 300), ("type", "Type", 60),
                            ("vendor", "Supplier", 170), ("lines", "Lines", 60),
                            ("loaded", "Loaded", 150), ("original", "Original", 130)]:
            self.files_tree.heading(c, text=label)
            self.files_tree.column(c, width=w,
                                   anchor="e" if c == "lines" else "w")
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.files_tree.yview)
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
        self._handle_files(self._split_dnd_paths(event.data))

    @staticmethod
    def _split_dnd_paths(data: str) -> List[str]:
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

    # ── file import ─────────────────────────────────────────────────────
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
                with open(path, "rb") as f:
                    data = f.read()
            except OSError as exc:
                self._log(f"✗ Could not read {name}: {exc}")
                continue
            fhash = QuoteDB.file_hash(path)
            dup = self.db.find_by_hash(fhash)
            if dup:
                self._log(f"• {name} already loaded as “{dup['filename']}”. Skipped.")
                continue
            try:
                quote = parse_file(path)
            except Exception as exc:   # noqa: BLE001
                self._log(f"✗ Failed to parse {name}: {exc}")
                messagebox.showerror("Parse error", f"Could not parse {name}:\n{exc}")
                continue
            self._log(f"→ {name}: extracted {len(quote.lines)} line(s). Opening review…")
            self._open_review(quote, name, fhash, data)

    def _open_review(self, quote, name, fhash, data):
        def on_save(edited):
            self.db.save_quote(edited, name, fhash, original_bytes=data)
            self._log(f"✓ Saved {name}: {len(edited.lines)} line(s) "
                      f"(supplier: {edited.vendor or 'n/a'}).")
            self.refresh_all()
        ReviewDialog(self.root, quote, name, on_save)

    # ── refresh ─────────────────────────────────────────────────────────
    def refresh_all(self):
        self._refresh_kpis()
        self._refresh_filter_choices()
        self.refresh_log()
        self.refresh_study()
        self.refresh_files()
        size = (os.path.getsize(self.db_path) / 1024
                if os.path.exists(self.db_path) else 0)
        self.db_lbl.config(text=f"Database:\n{self.db_path}\n{size:,.0f} KB")

    def _refresh_kpis(self):
        k = self.db.kpis()
        for key in ("parts", "vendors", "lines", "files"):
            self.kpi_cards[key].config(text=str(k[key]))
        bp = k["best_price"]
        self.kpi_cards["best_price"].config(
            text="—" if bp is None else f"{bp:,.2f}")

    def _refresh_filter_choices(self):
        vendors = ["(all)"] + self.db.vendors()
        parts = ["(all)"] + self.db.part_numbers()
        for cb, var, values in [
                (self.vendor_cb, self.vendor_var, vendors),
                (self.study_vendor_cb, self.study_vendor_var, vendors),
                (self.log_part_cb, self.log_part_var, parts),
                (self.study_part_cb, self.study_part_var, parts)]:
            cb["values"] = values
            if var.get() not in values:
                var.set("(all)")

    def _clear_log_filters(self):
        self.search_var.set("")
        self.log_part_var.set("(all)")
        self.vendor_var.set("(all)")
        self.refresh_log()

    @staticmethod
    def _sel(var):
        v = var.get()
        return "" if v == "(all)" else v

    def refresh_log(self):
        quantities = self.db.distinct_quantities()
        rows = self.db.quote_log(search=self.search_var.get().strip(),
                                 vendor=self._sel(self.vendor_var),
                                 part_number=self._sel(self.log_part_var))
        base = [("part_number", "Part #", 130), ("vendor", "Supplier", 150),
                ("description", "Description", 180), ("material", "Material", 100),
                ("lead_time", "Lead Time", 90)]
        qcols = [(f"q{q:g}", f"@{q:g}", 80) for q in quantities]
        self.log_tree = self._rebuild_tree(self.log_wrap, self.log_tree,
                                           base + qcols,
                                           right_align={c[0] for c in qcols})
        for r in rows:
            vals = [r["part_number"], r["vendor"] or "", r["description"] or "",
                    r["material"] or "", r["lead_time"] or ""]
            for q in quantities:
                p = r["breaks"].get(q)
                vals.append("" if p is None else f"{p:,.2f}")
            self.log_tree.insert("", "end", iid=str(r["id"]), values=vals)

    def refresh_study(self):
        data = self.db.study(part_number=self._sel(self.study_part_var),
                             vendor=self._sel(self.study_vendor_var))
        quantities = sorted({q for g in data for s in g["suppliers"]
                             for q in s["breaks"]})

        # Rebuild a tree-mode Treeview: parent = part, children = suppliers.
        if self.study_tree is not None:
            self.study_tree.master.destroy()
        holder = ttk.Frame(self.study_wrap, style="Card.TFrame")
        holder.pack(fill="both", expand=True)
        # Decision fields (supplier, material, delivery) sit on the left so
        # price and lead time are visible together; the price columns extend
        # to the right.
        cols = ["material", "lead_time", "tooling", "moq"] + \
               [f"q{q:g}" for q in quantities]
        tree = ttk.Treeview(holder, columns=cols, show="tree headings")
        tree.heading("#0", text="Part #  /  Supplier")
        tree.column("#0", width=230, stretch=False)
        for key, label, w, anchor in [("material", "Material", 150, "w"),
                                      ("lead_time", "Lead Time", 110, "w"),
                                      ("tooling", "Tooling", 75, "e"),
                                      ("moq", "MOQ", 65, "e")]:
            tree.heading(key, text=label)
            tree.column(key, width=w, anchor=anchor, stretch=False)
        for q in quantities:
            tree.heading(f"q{q:g}", text=f"@{q:g}")
            tree.column(f"q{q:g}", width=90, anchor="e", stretch=False)
        vs = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        hs = ttk.Scrollbar(holder, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        tree.tag_configure("part", background=theme.GRAY_MID, font=theme.FONT_BOLD)

        for g in data:
            label = g["part_number"]
            if g["description"]:
                label += f"   —   {g['description']}"
            parent = tree.insert("", "end", text=label,
                                 values=[""] * len(cols), open=True,
                                 tags=("part",))
            for s in g["suppliers"]:
                lead = s["lead_time"] or ""
                if (s["lead_weeks"] is not None and g["best_lead"] is not None
                        and s["lead_weeks"] == g["best_lead"]):
                    lead = BEST + lead
                vals = [s["material"] or "", lead,
                        "" if s["tooling"] is None else f"{s['tooling']:,.2f}",
                        "" if s["moq"] is None else f"{s['moq']:g}"]
                for q in quantities:
                    price = s["breaks"].get(q)
                    if price is None:
                        vals.append("")
                    else:
                        mark = BEST if g["best_price"].get(q) == price else ""
                        vals.append(f"{mark}{price:,.2f}")
                tree.insert(parent, "end", text=f"   {s['vendor'] or '—'}",
                            values=vals)
        self.study_tree = tree

    def _expand_study(self, opened: bool):
        if self.study_tree is None:
            return
        for iid in self.study_tree.get_children():
            self.study_tree.item(iid, open=opened)

    def refresh_files(self):
        for iid in self.files_tree.get_children():
            self.files_tree.delete(iid)
        for f in self.db.list_files():
            if f["has_original"]:
                kb = (f["original_size"] or 0) / 1024
                orig = f"Yes ({kb:,.0f} KB)"
            else:
                orig = "purged / not stored"
            self.files_tree.insert(
                "", "end", iid=str(f["id"]),
                values=(f["filename"], (f["source_type"] or "").upper(),
                        f["vendor"] or "", f["line_count"], f["loaded_at"] or "",
                        orig))

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

    # ── row actions ─────────────────────────────────────────────────────
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

    def _selected_file_id(self):
        sel = self.files_tree.selection()
        return int(sel[0]) if sel else None

    def _delete_file(self):
        fid = self._selected_file_id()
        if fid is None:
            messagebox.showinfo("Remove file", "Select a file first.")
            return
        if messagebox.askyesno("Remove file",
                               "Remove this file and all its quote lines?"):
            self.db.delete_file(fid)
            self.refresh_all()

    def _download_original(self):
        fid = self._selected_file_id()
        if fid is None:
            messagebox.showinfo("Download", "Select a file first.")
            return
        orig = self.db.get_original(fid)
        if orig is None:
            messagebox.showinfo("Download",
                                "The original file is no longer stored "
                                "(not saved, or purged after 6 months).")
            return
        filename, data = orig
        dest = filedialog.asksaveasfilename(
            title="Save original quote file", initialfile=filename,
            defaultextension=os.path.splitext(filename)[1])
        if not dest:
            return
        try:
            with open(dest, "wb") as f:
                f.write(data)
        except OSError as exc:
            messagebox.showerror("Download failed", str(exc))
            return
        self._log(f"✓ Downloaded original: {os.path.basename(dest)}")
        messagebox.showinfo("Downloaded", f"Saved:\n{dest}")

    def _open_original(self):
        fid = self._selected_file_id()
        if fid is None:
            messagebox.showinfo("Open", "Select a file first.")
            return
        orig = self.db.get_original(fid)
        if orig is None:
            messagebox.showinfo("Open", "The original file is no longer stored.")
            return
        filename, data = orig
        tmp = os.path.join(tempfile.gettempdir(), filename)
        try:
            with open(tmp, "wb") as f:
                f.write(data)
        except OSError as exc:
            messagebox.showerror("Open failed", str(exc))
            return
        open_path(tmp)

    # ── database menu actions ───────────────────────────────────────────
    def _set_db_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder for the database")
        if not folder:
            return
        target = os.path.join(folder, config.DB_FILENAME)
        if os.path.abspath(target) == os.path.abspath(self.db_path):
            return
        if os.path.exists(target):
            if not messagebox.askyesno(
                    "Use existing database",
                    f"A database already exists in that folder:\n{target}\n\n"
                    "Switch to it? (Your current data stays in the old location.)"):
                return
        else:
            try:
                self.db.save_as(target)
            except Exception as exc:   # noqa: BLE001
                messagebox.showerror("Could not move database", str(exc))
                return
        config.set_db_path(target)
        self.db = QuoteDB(target)
        self.db_path = target
        self.db.purge_old_originals()
        self.refresh_all()
        self._log(f"✓ Database location set to {target}")
        messagebox.showinfo("Database moved",
                            f"The app now uses:\n{target}")

    def _backup_db(self):
        folder = filedialog.askdirectory(title="Choose a folder for the backup")
        if not folder:
            return
        try:
            path = self.db.backup_to(folder)
        except Exception as exc:   # noqa: BLE001
            messagebox.showerror("Backup failed", str(exc))
            return
        self._log(f"✓ Backup written: {os.path.basename(path)}")
        messagebox.showinfo("Backup complete", f"Saved a copy to:\n{path}")

    def _purge_now(self):
        n = self.db.purge_old_originals()
        self.refresh_files()
        messagebox.showinfo(
            "Purge complete",
            f"Removed {n} original file(s) older than 6 months.\n"
            "The quote data itself is always kept.")

    def _about(self):
        messagebox.showinfo(
            "HAWE Quote Tracker",
            "Supplier price tracker.\n\n"
            "• Import PDF / Excel / CSV quotes by drag-and-drop.\n"
            "• Review the extracted data before it is saved.\n"
            "• Study tab compares suppliers per part on price AND delivery.\n"
            "• Original files are stored for re-download and auto-removed after "
            f"6 months (~{ORIGINAL_RETENTION_DAYS} days).\n"
            "• Use the Database menu to choose the database folder or back it up.")

    # ── excel export ────────────────────────────────────────────────────
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
                    "Lead Time", "Tooling", "Currency"] +
                   [f"@{q:g}" for q in quantities] + ["Notes", "File"])
        ws.append(headers)
        hf = Font(color="FFFFFF", bold=True)
        fill = PatternFill("solid", fgColor="1A1A1A")
        for cell in ws[1]:
            cell.font = hf
            cell.fill = fill
        for r in rows:
            row = [r["part_number"], r["vendor"], r["description"], r["material"],
                   r["moq"], r["lead_time"], r["tooling"], r["currency"]]
            row += [r["breaks"].get(q) for q in quantities]
            row += [r["notes"], r["filename"]]
            ws.append(row)
        ws.freeze_panes = "A2"

        cmp_ws = wb.create_sheet("Study")
        cmp_ws.append(["Part #", "Supplier", "Material"] +
                      [f"@{q:g}" for q in quantities] +
                      ["Lead Time", "Lead (wks)", "Tooling", "MOQ"])
        for cell in cmp_ws[1]:
            cell.font = hf
            cell.fill = fill
        best_fill = PatternFill("solid", fgColor="C8E6C9")
        for g in self.db.study():
            for s in g["suppliers"]:
                line = [g["part_number"], s["vendor"], s["material"]]
                line += [s["breaks"].get(q) for q in quantities]
                line += [s["lead_time"], s["lead_weeks"], s["tooling"], s["moq"]]
                cmp_ws.append(line)
                r_idx = cmp_ws.max_row
                for j, q in enumerate(quantities):
                    price = s["breaks"].get(q)
                    if price is not None and g["best_price"].get(q) == price:
                        cmp_ws.cell(row=r_idx, column=4 + j).fill = best_fill
                if (s["lead_weeks"] is not None
                        and s["lead_weeks"] == g["best_lead"]):
                    cmp_ws.cell(row=r_idx,
                                column=4 + len(quantities)).fill = best_fill
        wb.save(path)

    # ── activity log ────────────────────────────────────────────────────
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M")
        self.activity.config(state="normal")
        self.activity.insert("1.0", f"[{ts}]  {msg}\n")
        self.activity.config(state="disabled")

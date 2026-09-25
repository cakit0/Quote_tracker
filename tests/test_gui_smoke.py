"""
Head-less GUI smoke test (run under Xvfb with python3.12).

Constructs the real Tk window, loads sample quotes, exercises the dynamic
tables / KPIs / comparison, drives the review dialog's collect logic and the
Excel export - all without a human.  Catches widget-construction and
refresh-time errors that the pure-logic tests can't.

    xvfb-run -a python3.12 -m tests.test_gui_smoke
"""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk                                         # noqa: E402
from quote_tracker.parsers import parse_file                 # noqa: E402
from quote_tracker.database import QuoteDB                   # noqa: E402
from quote_tracker.gui import QuoteTrackerApp                # noqa: E402
from quote_tracker.review_dialog import ReviewDialog         # noqa: E402
from quote_tracker.edit_dialog import EditLineDialog          # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
failures = []


def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def main():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "smoke.db")

    # Pre-load two files directly so the window opens with data.  The first is
    # stored with its original bytes so the download/retention checks below
    # don't depend on the optional (git-ignored) sample sheets.
    db = QuoteDB(db_path)
    for fn in ("vendor_A_wide.xlsx", "vendor_B_long.csv"):
        path = os.path.join(SAMPLES, fn)
        q = parse_file(path)
        with open(path, "rb") as fh:
            db.save_quote(q, fn, file_hash=fn, original_bytes=fh.read())

    root = tk.Tk()
    root.withdraw()   # don't actually map the window
    app = QuoteTrackerApp(root, db_path=db_path, dnd_enabled=False)
    root.update_idletasks()

    print("\n[main window]")
    check(app.kpi_cards["files"].cget("text") == "2", "KPI files == 2")
    check(app.kpi_cards["parts"].cget("text") == "3", "KPI parts == 3")
    check(app.log_tree is not None, "quote-log table built")
    # 3 lines from vendor_A + 2 lines from vendor_B = 5 quote lines total.
    check(len(app.log_tree.get_children()) == 5, "5 rows in quote log")
    check(app.study_tree is not None, "study table built")
    check(len(app.files_tree.get_children()) == 2, "2 files listed")

    print("\n[dynamic columns follow the data]")
    # Quote log should have one @column per distinct quantity (100,500,1000,5000).
    # Quantity columns are q<number>; don't confuse them with "quote_number".
    qcols = [c for c in app.log_tree["columns"] if re.fullmatch(r"q[\d.]+", c)]
    check(len(qcols) == 4, f"4 quantity columns in log (got {len(qcols)})")

    print("\n[filter]")
    app.search_var.set("13-30006")   # only exists in vendor_A
    root.update_idletasks()
    check(len(app.log_tree.get_children()) == 1, "search filters to 1 row")
    app.search_var.set("")
    root.update_idletasks()

    print("\n[study tab + delivery comparison]")
    # Load the multi-supplier overview sheet so the Study tab has real groups.
    ov = os.path.join(SAMPLES, "overview_sheet.xlsx")
    if os.path.exists(ov):
        with open(ov, "rb") as fh:
            db.save_quote(parse_file(ov), "overview_sheet.xlsx",
                          file_hash="ovh", original_bytes=fh.read())
        app.refresh_all()
        root.update_idletasks()
        check(app.study_tree is not None, "study tree built")
        parents = app.study_tree.get_children()
        check(len(parents) > 0, f"study has part groups (got {len(parents)})")
        # Find the 17-30034-CN group and verify a star marks the best price.
        starred = any(
            "★" in " ".join(str(v) for v in app.study_tree.item(child, "values"))
            for p in parents for child in app.study_tree.get_children(p))
        check(starred, "best price/delivery is marked with a star")

    print("\n[files: original stored + retrievable]")
    files = app.db.list_files()
    fid = files[0]["id"]
    check(any(f["has_original"] for f in files), "at least one original stored")
    orig = app.db.get_original(fid)
    check(orig is not None, "original file retrievable for download")

    print("\n[backup]")
    bdir = tempfile.mkdtemp()
    bpath = app.db.backup_to(bdir)
    check(os.path.exists(bpath) and os.path.getsize(bpath) > 0, "backup written")

    print("\n[review dialog collect]")
    q = parse_file(os.path.join(SAMPLES, "vendor_C_quote.pdf"))
    saved = {}

    def on_save(edited):
        saved["quote"] = edited
    dlg = ReviewDialog(root, q, "vendor_C_quote.pdf", on_save)
    root.update_idletasks()
    # Simulate a user edit: change the first part number via the grid API.
    first = dlg.tree.get_children()[0]
    dlg.tree.set(first, "part_number", "EDITED-001")
    dlg.vendor_var.set("Rapid Tooling Inc")
    dlg._save()
    root.update_idletasks()
    check("quote" in saved, "on_save callback fired")
    check(saved["quote"].lines[0].part_number == "EDITED-001", "grid edit captured")
    check(saved["quote"].vendor == "Rapid Tooling Inc", "vendor captured")

    # Persist it and confirm the window refreshes (file count grows by one).
    before = int(app.kpi_cards["files"].cget("text"))
    db.save_quote(saved["quote"], "vendor_C_quote.pdf")
    app.refresh_all()
    root.update_idletasks()
    after = int(app.kpi_cards["files"].cget("text"))
    check(after == before + 1, f"file count grew after save ({before}->{after})")

    print("\n[hide empty columns]")
    # vendor_A/B data has no tooling or MOQ, so those columns must be hidden.
    shown = list(app.log_tree["displaycolumns"])
    all_keys = list(app.log_tree["columns"])
    check("part_number" in shown, "populated column stays visible")
    empties = [k for k in all_keys
               if all(not str(app.log_tree.set(i, k)).strip()
                      for i in app.log_tree.get_children())]
    check(all(k not in shown for k in empties),
          f"blank columns auto-hidden ({len(empties)} hidden)")
    # A user can force a hidden column back on.
    if empties:
        app.log_shown_manual.add(empties[0])
        app.refresh_log()
        check(empties[0] in list(app.log_tree["displaycolumns"]),
              "user can re-show a hidden column")
        app.log_shown_manual.clear()
        app.refresh_log()

    print("\n[edit a saved line]")
    first = app.log_tree.get_children()[0]
    line_id = int(first)
    before = app.db.get_line(line_id)
    check(before is not None, "line loaded for editing")
    holder = {}
    dlg = EditLineDialog(root, before,
                         lambda v, b: holder.update(values=v, breaks=b))
    root.update_idletasks()
    dlg.vars["part_number"].set("EDITED-PN")
    dlg.vars["quote_number"].set("QN-123")
    dlg._save()
    root.update_idletasks()
    app.db.update_line(line_id, holder["values"], holder["breaks"])
    after = app.db.get_line(line_id)
    check(after["part_number"] == "EDITED-PN", "edited part number saved")
    check(after["quote_number"] == "QN-123", "quote number saved")
    check(after["breaks"] == before["breaks"], "price breaks preserved")

    print("\n[excel export]")
    out = os.path.join(tmp, "export.xlsx")
    app._write_excel(out, app.db.export_rows())
    check(os.path.exists(out) and os.path.getsize(out) > 0, "export.xlsx written")
    from openpyxl import load_workbook
    wb = load_workbook(out)
    check("Quote Log" in wb.sheetnames and "Study" in wb.sheetnames,
          "export has Quote Log + Study sheets")

    root.destroy()
    print("\n" + "=" * 50)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    print("ALL GUI SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()

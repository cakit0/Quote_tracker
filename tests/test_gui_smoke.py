"""
Head-less GUI smoke test (run under Xvfb with python3.12).

Constructs the real Tk window, loads sample quotes, exercises the dynamic
tables / KPIs / comparison, drives the review dialog's collect logic and the
Excel export - all without a human.  Catches widget-construction and
refresh-time errors that the pure-logic tests can't.

    xvfb-run -a python3.12 -m tests.test_gui_smoke
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk                                         # noqa: E402
from quote_tracker.parsers import parse_file                 # noqa: E402
from quote_tracker.database import QuoteDB                   # noqa: E402
from quote_tracker.gui import QuoteTrackerApp                # noqa: E402
from quote_tracker.review_dialog import ReviewDialog         # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
failures = []


def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        failures.append(msg)


def main():
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, "smoke.db")

    # Pre-load two files directly so the window opens with data.
    db = QuoteDB(db_path)
    for fn in ("vendor_A_wide.xlsx", "vendor_B_long.csv"):
        q = parse_file(os.path.join(SAMPLES, fn))
        db.save_quote(q, fn)

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
    qcols = [c for c in app.log_tree["columns"] if c.startswith("q")]
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

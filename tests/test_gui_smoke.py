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
    check(app.cmp_tree is not None, "comparison table built")
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

    # Persist it and confirm the window refreshes to 3 files.
    db.save_quote(saved["quote"], "vendor_C_quote.pdf")
    app.refresh_all()
    root.update_idletasks()
    check(app.kpi_cards["files"].cget("text") == "3", "KPI files == 3 after save")

    print("\n[excel export]")
    out = os.path.join(tmp, "export.xlsx")
    app._write_excel(out, app.db.export_rows())
    check(os.path.exists(out) and os.path.getsize(out) > 0, "export.xlsx written")
    from openpyxl import load_workbook
    wb = load_workbook(out)
    check("Quote Log" in wb.sheetnames and "Best Price" in wb.sheetnames,
          "export has Quote Log + Best Price sheets")

    root.destroy()
    print("\n" + "=" * 50)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    print("ALL GUI SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()

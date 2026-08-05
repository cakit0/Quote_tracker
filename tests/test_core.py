"""
Head-less tests for the parsing + storage pipeline.

Generates realistic sample quote files (xlsx, csv, pdf) in ./samples, parses
them, stores them in a temp SQLite DB and checks the comparison/KPIs.  Runs
without any display, so it works in CI / on this Linux box even though the GUI
itself is Windows/Tk.

    python -m tests.test_core
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quote_tracker.parsers import parse_file, parse_number   # noqa: E402
from quote_tracker.database import QuoteDB                    # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
os.makedirs(SAMPLES, exist_ok=True)

failures = []


def check(cond, msg):
    if cond:
        print(f"  PASS  {msg}")
    else:
        print(f"  FAIL  {msg}")
        failures.append(msg)


# ── sample generators ───────────────────────────────────────────────────────
def make_excel_wide():
    from openpyxl import Workbook
    path = os.path.join(SAMPLES, "vendor_A_wide.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.append(["Vendor: Precision Machining Co"])
    ws.append([])
    ws.append(["Part #", "Description", "Material", "MOQ", "100", "500", "1000", "5000"])
    ws.append(["13-30004", "Housing bracket", "AL 6061", 100, 12.50, 9.80, 8.25, 6.90])
    ws.append(["13-30005", "Cover plate", "SS 304", 50, 22.00, 18.50, 16.00, 13.25])
    ws.append(["13-30006", "Shaft pin", "AL 7075", 100, 4.10, 3.55, 3.10, 2.60])
    wb.save(path)
    return path


def make_csv_long():
    path = os.path.join(SAMPLES, "vendor_B_long.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("Supplier: Global Parts Ltd\n")
        f.write("Part Number,Quantity,Unit Price\n")
        f.write("13-30004,100,$11.90\n")
        f.write("13-30004,500,$9.20\n")
        f.write("13-30004,1000,$7.95\n")
        f.write("13-30005,100,$23.50\n")
        f.write("13-30005,1000,$15.40\n")
    return path


def make_pdf_table():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    path = os.path.join(SAMPLES, "vendor_C_quote.pdf")
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [
        ["Part #", "Description", "100", "500", "1000"],
        ["13-30004", "Housing bracket", "13.20", "10.10", "8.60"],
        ["13-30005", "Cover plate", "21.00", "17.90", "15.10"],
        ["13-30006", "Shaft pin", "3.90", "3.40", "2.95"],
    ]
    t = Table(data)
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    doc.build([Paragraph("Vendor: Rapid Tooling Inc", styles["Heading2"]),
               Spacer(1, 12), t])
    return path


# ── number parser ───────────────────────────────────────────────────────────
def test_number_parser():
    print("\n[number parser]")
    check(parse_number("$1,234.56") == 1234.56, "US grouped -> 1234.56")
    check(parse_number("1.234,56") == 1234.56, "EU grouped -> 1234.56")
    check(parse_number("12,50 €") == 12.50, "EU decimal comma -> 12.50")
    check(parse_number("9.80") == 9.80, "plain decimal")
    check(parse_number("") is None, "empty -> None")
    check(parse_number("N/A") is None, "text -> None")


def test_parsers_and_db():
    xlsx = make_excel_wide()
    csvf = make_csv_long()
    pdf = make_pdf_table()

    print("\n[excel wide]")
    q = parse_file(xlsx)
    check(len(q.lines) == 3, f"3 lines parsed (got {len(q.lines)})")
    check(q.quantities == [100, 500, 1000, 5000], f"quantities {q.quantities}")
    check(abs(q.lines[0].price_at(1000) - 8.25) < 1e-9, "13-30004 @1000 = 8.25")
    check("Precision" in q.vendor, f"vendor inferred: {q.vendor!r}")

    print("\n[csv long]")
    q2 = parse_file(csvf)
    check(len(q2.lines) == 2, f"2 grouped parts (got {len(q2.lines)})")
    l0 = next(l for l in q2.lines if l.part_number == "13-30004")
    check(len(l0.breaks) == 3, f"13-30004 has 3 breaks (got {len(l0.breaks)})")
    check(abs(l0.price_at(500) - 9.20) < 1e-9, "13-30004 @500 = 9.20")

    print("\n[pdf table]")
    q3 = parse_file(pdf)
    check(len(q3.lines) == 3, f"3 lines from PDF table (got {len(q3.lines)})")
    check(q3.quantities == [100, 500, 1000], f"pdf quantities {q3.quantities}")

    print("\n[database + comparison]")
    tmp = tempfile.mkdtemp()
    db = QuoteDB(os.path.join(tmp, "test.db"))
    db.save_quote(q, os.path.basename(xlsx))
    db.save_quote(q2, os.path.basename(csvf))
    db.save_quote(q3, os.path.basename(pdf))
    k = db.kpis()
    check(k["files"] == 3, f"3 files stored (got {k['files']})")
    check(k["parts"] == 3, f"3 distinct parts (got {k['parts']})")

    comp = db.comparison()
    part = next(c for c in comp if c["part_number"] == "13-30004")
    # @1000: A=8.25, B=7.95, C=8.60 -> best is B 7.95
    best_price, best_vendor = part["best"][1000]
    check(abs(best_price - 7.95) < 1e-9, f"best @1000 for 13-30004 = 7.95 (got {best_price})")
    check("Global" in best_vendor, f"best vendor is Global Parts (got {best_vendor!r})")


def test_real_quote_optional():
    """Regression test against a real supplier PDF (M&W quote 54446).

    The PDF is intentionally NOT committed (it contains a supplier's confidential
    pricing), so this test is skipped when the file is absent.
    """
    path = os.path.join(SAMPLES, "real_q54446.pdf")
    print("\n[real supplier PDF]")
    if not os.path.exists(path):
        print("  SKIP  real_q54446.pdf not present")
        return
    q = parse_file(path)
    breaks = {b.quantity: b.unit_price for ln in q.lines for b in ln.breaks}
    check(q.vendor == "M&W", f"vendor is the supplier M&W (got {q.vendor!r})")
    check(len(q.lines) == 1 and q.lines[0].part_number == "26-1114",
          "part number 26-1114 extracted")
    check(breaks == {1: 837.24, 50: 148.67, 100: 135.66, 500: 129.51},
          f"quantity breaks 1/50/100/500 read from text (got {breaks})")
    check(not q.warnings, f"no parse warnings (got {q.warnings})")


def test_real_quotes_supplier_and_part():
    """Supplier + part-number extraction across the varied real PDF formats.

    These files carry confidential pricing and are not committed, so each check
    is skipped when its file is absent.  Expected values assert the supplier
    name and the first part number only (prices are reviewed by the user).
    """
    print("\n[real quotes: supplier + part number]")
    cases = {
        "real_q54446.pdf":  ("M&W", "26-1114"),
        "real_q54497.pdf":  ("M&W", "26-20027-CA"),
        "real_6274.pdf":    ("Custom Hydraulics Inc.", "25-20045-US"),
        "real_6284.pdf":    ("Custom Hydraulics Inc.", "EC-000072-US"),
        "real_nd.pdf":      ("NEW DIMENSIONS PRECISION MACHINING, INC.", "3253368"),
        "real_q19054.pdf":  ("LBG Machine, Inc.", "MF19-0195-R0"),
        "real_b26028.pdf":  ("Daman", None),          # part not reliably in text
        "real_yoye.pdf":    ("NINGBO YOYE HYDRAULICS CO.,LTD", "25-20038-US"),
    }
    for fname, (exp_vendor, exp_part) in cases.items():
        path = os.path.join(SAMPLES, fname)
        if not os.path.exists(path):
            print(f"  SKIP  {fname} not present")
            continue
        q = parse_file(path)
        check(q.vendor == exp_vendor,
              f"{fname}: supplier {exp_vendor!r} (got {q.vendor!r})")
        if exp_part is not None:
            got = q.lines[0].part_number if q.lines else None
            check(got == exp_part, f"{fname}: part {exp_part!r} (got {got!r})")
        # HAWE (the customer) must never be recorded as the supplier.
        check("hawe" not in (q.vendor or "").lower(),
              f"{fname}: customer not used as supplier")


if __name__ == "__main__":
    test_number_parser()
    test_parsers_and_db()
    test_real_quote_optional()
    test_real_quotes_supplier_and_part()
    print("\n" + "=" * 50)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    print("ALL TESTS PASSED")

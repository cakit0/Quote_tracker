# HAWE Quote Tracker — Desktop Edition

A **native Windows desktop app** for tracking supplier prices. Drag a supplier
quote — **PDF, Excel or CSV** — onto the window and it extracts the part
numbers, quantity breaks and prices, lets you review/correct them, and stores
everything so you can compare suppliers side by side.

> This is a rebuild of the original Manus version. The old one was a Flask **web
> server that opened a browser tab** and only read Excel files. This version is a
> **real desktop window** (no browser, no server) that also reads **PDF quotes**,
> and it uses a **flexible quantity model** so any set of quantity breaks works —
> not just a fixed 50/100/…/5000 list.

---

## Two ways to run it

### Option A — just run it (needs Python once)
1. Install **Python 3.9+** from <https://www.python.org/downloads/> and tick
   **“Add Python to PATH”** during setup.
2. Double-click **`START_QUOTE_TRACKER.bat`**.
   On the first run it installs the few required packages automatically, then
   opens the app window. Every run after that is instant.

### Option B — build a standalone `.exe` (no Python needed on other PCs)
1. On a PC that has Python, double-click **`build_exe.bat`**.
2. After a few minutes you get **`dist\QuoteTracker.exe`** — a single file.
3. Copy that `.exe` anywhere (e.g. your OneDrive Quoting folder) and
   double-click it. No Python required on that machine.

Either way, the database file **`hawe_quotes.db`** is created **next to the app**
so it can live in a shared OneDrive folder. Back it up by copying that file.

---

## Using it

- **Import tab** — drag files onto the drop zone (or click *Browse files…*).
  Each file opens a **Review** window showing what was extracted. Fix anything
  that’s wrong (double-click a cell to edit), set the supplier name, then
  **Save to database**. Nothing is stored until you confirm — important for
  PDFs, where extraction is a best guess.
- **Quote Log tab** — every quote line, all suppliers, searchable and filterable
  by supplier. One column per quantity break.
- **Comparison tab** — for each part, the **lowest unit price at every quantity**
  and **which supplier** offers it.
- **Files tab** — the files you’ve loaded; remove one to remove its lines.
- **Export to Excel** — writes a two-sheet workbook (full Quote Log + Best Price).

Loading the same file twice is detected (by content hash) and skipped.

---

## Supported files

| Type | Extension | How it’s read |
|---|---|---|
| PDF | `.pdf` | Ruled tables are extracted first; if a PDF has no table, price breaks are pulled from the text as a fallback. |
| Excel | `.xlsx` `.xlsm` | Header row auto-detected; quantity-break columns recognised. |
| CSV / text | `.csv` `.tsv` `.txt` | Same column detection; US and European number formats handled. |

Two table shapes are understood automatically:

- **Wide** — one row per part, a column per quantity (`Part # | Desc | 100 | 500 | 1000 …`)
- **Long** — one row per quantity break (`Part # | Quantity | Unit Price`)

Because PDFs vary so much, the **Review** step is where you get the final say —
treat auto-extraction as a fast first draft, not gospel.

---

## Requirements

- Windows (also runs on macOS/Linux via `python -m quote_tracker.main`)
- Python 3.9+ **for Option A / building** (not needed to run a built `.exe`)
- Packages (installed automatically): `pdfplumber`, `openpyxl`, `tkinterdnd2`

`tkinterdnd2` powers drag-and-drop. If it isn’t present the app still works
fully — just use the **Browse files…** button instead.

---

## Project layout

```
quote_tracker/
  main.py          entry point (creates the window)
  gui.py           main window: tabs, KPIs, tables, export
  review_dialog.py editable review grid shown before saving
  parsers.py       PDF / Excel / CSV extraction
  database.py      SQLite storage (flexible quantity model)
  models.py        shared data classes
  theme.py         HAWE colours and ttk styling
tests/
  test_core.py     head-less parser + database tests
  test_gui_smoke.py head-less GUI construction test (needs Tk)
samples/           example quote files (xlsx / csv / pdf) to try it out
START_QUOTE_TRACKER.bat   run it (Option A)
build_exe.bat             build QuoteTracker.exe (Option B)
```

### Data model
`quote_files` → `quote_lines` → `price_breaks`. Prices are stored as
`(quantity, unit_price)` pairs, so a quote can carry any quantity breaks at all.

---

## Running the tests (developers)

```bash
python -m tests.test_core          # parsers + database, no display needed
python -m tests.test_gui_smoke     # GUI construction (needs Tkinter/display)
```

---

## Version

v2.0 — Desktop Edition. Adds PDF support, a native window, a review-before-save
step, and a flexible quantity model.

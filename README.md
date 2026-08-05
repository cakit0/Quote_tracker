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

### “Windows protected your PC” (SmartScreen)

This red dialog is **not** a virus detection. Windows shows it for any program
downloaded from the internet that is not **code-signed** and has no download
history (“Unknown publisher”). Options, cheapest first:

**1. Run it anyway (per PC, free)**
Click **More info → Run anyway**. Windows remembers it for that copy of the file.

**2. Unblock the download (per PC, free, avoids the dialog entirely)**
Windows tags downloaded files with a “mark of the web”. Remove it *before*
extracting and the warning does not appear at all:
- Right-click the downloaded **.zip → Properties →** tick **Unblock → OK**, then
  extract. (Unblocking the zip clears the tag on everything inside.)
- Or in PowerShell: `Unblock-File .\QuoteTracker-windows.zip`

**3. Have IT distribute it (whole company, free if you have the tooling)**
A file pushed through Intune/SCCM/GPO or copied from an internal file share
does not carry the internet tag, so nobody sees the warning. IT can also add a
SmartScreen/Defender allow-list entry for the app.

**4. Code-sign the `.exe` (permanent, paid — the real fix)**
A code-signing certificate issued to HAWE removes the warning for everyone and
shows “HAWE Manufacturing US Inc” as the publisher instead of “Unknown”.
- **OV certificate** (~$200–400/yr): the warning stops once the signed app
  builds up download reputation (days to weeks).
- **EV certificate** (~$400–700/yr, on a hardware token): trusted **immediately**,
  no reputation period.

The build is already wired for this — no code changes needed. Add two
repository secrets and every build is signed automatically:

| Secret | Value |
|---|---|
| `CERT_PFX_BASE64` | the `.pfx` certificate, base64-encoded (`certutil -encode cert.pfx cert.txt`) |
| `CERT_PASSWORD` | the certificate’s password |

Note that each *new* unsigned build is a new file, so its reputation starts over
— another reason signing is the durable answer if this gets rolled out widely.

**5. Skip the `.exe` entirely (free)**
Run via **Option A** (`START_QUOTE_TRACKER.bat` with Python installed).
SmartScreen’s app-reputation check does not apply, so no warning appears.

### Option C — download a pre-built `.exe` (no Python at all)
A GitHub Actions workflow (`.github/workflows/build-windows-exe.yml`) builds the
Windows `.exe` on every push. To download it:
1. Open the repo’s **Actions** tab → the latest **Build Windows EXE** run.
2. Under **Artifacts**, download **`QuoteTracker-windows`** (a zip containing
   `QuoteTracker.exe`).
3. Unzip and double-click `QuoteTracker.exe`.

Either way, the database file **`hawe_quotes.db`** is created **next to the app**
so it can live in a shared OneDrive folder. Back it up by copying that file.

---

## Using it

- **Import tab** — drag files onto the drop zone (or click *Browse files…*).
  Each file opens a **Review** window showing what was extracted. Fix anything
  that’s wrong (double-click a cell to edit), set the supplier name, then
  **Save to database**. Nothing is stored until you confirm — important for
  PDFs, where extraction is a best guess.
- **Quote Log tab** — every quote line, all suppliers. Filter by **Part #**,
  **Supplier** and free-text **Search** (combine them; *Clear filters* resets).
  One column per quantity break, plus the supplier’s own **Quote #**.
  - **Blank columns hide themselves.** A quantity column that no visible row
    uses is hidden automatically, so the table stays tidy when quotes use
    different quantity breaks.
  - **Right-click a column heading to hide it**, or use **Columns…** to tick
    exactly which columns to show (*Show all* brings everything back).
  - **Edit line** (or double-click a row) opens an editor for every field —
    part number, supplier, quote number, description, material, lead time,
    MOQ, tooling, notes — and the **price breaks** themselves, so you can fix
    anything that was mis-read or left blank after saving.
- **Study tab** — the decision table. For each part it lists **every supplier**
  side by side with quote number, material, lead time, tooling and price at each
  quantity (empty columns hide themselves here too).
  A **★** marks the **lowest price at each quantity** and the **fastest
  delivery**, so you can weigh price against lead time (e.g. one supplier
  cheaper but slower, another pricier but faster). Filter by Part # / Supplier.
- **Files tab** — the files you’ve loaded. **Download original** or **Open
  original** re-opens the exact file you imported. Originals are kept for
  re-download and **auto-removed after 6 months** (the quote data itself is
  always kept). Remove a file to remove its lines.
- **Database menu** — **Set database folder…** (move the `.db` to any folder,
  e.g. OneDrive), **Back up database now…** (timestamped copy), **Open database
  folder**, and a manual **purge** of originals older than 6 months.
- **Export to Excel** — writes a two-sheet workbook: full **Quote Log** and a
  **Study** sheet with best price / fastest delivery highlighted in green.

Loading the same file twice is detected (by content hash) and skipped.

Your chosen database folder is remembered between runs (stored in
`%APPDATA%\HAWEQuoteTracker\settings.json` on Windows).

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
  gui.py           main window: tabs, KPIs, tables, filters, export, DB menu
  review_dialog.py editable review grid shown before saving
  edit_dialog.py   edit a saved line + the column show/hide chooser
  parsers.py       PDF / Excel / CSV extraction
  database.py      SQLite storage (flexible quantity model, originals, study)
  config.py        remembers the chosen database folder between runs
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

v2.2 — Blank columns hide themselves (with a Columns… chooser and
right-click-to-hide), the supplier's quote number is captured and shown, and
any saved line can be edited afterwards.

v2.1 — Adds the Study comparison (price + delivery), Part #/Supplier filters,
downloadable originals with 6-month retention, and a choosable/backupable
database folder.

v2.0 — Desktop Edition. PDF support, a native window, a review-before-save
step, and a flexible quantity model.

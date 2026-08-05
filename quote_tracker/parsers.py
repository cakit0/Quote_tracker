"""
File parsers for the Quote Tracker.

Turns a PDF / Excel / CSV supplier quote into a ``ParsedQuote`` (see models.py).

The design goal is *forgiving* extraction: real supplier quotes are messy, so we
pull out as much structured data as we reasonably can and then let the user fix
the rest in the review grid before anything is saved.  Two common table shapes
are handled:

  * WIDE  - one row per part, a column per quantity break
            (Part # | Desc | 100 | 500 | 1000 ...)
  * LONG  - one row per quantity break for a single/named part
            (Quantity | Unit Price) with an optional Part # column

Supported extensions: .pdf .xlsx .xlsm .xltx .csv .tsv .txt
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import List, Optional, Sequence

from .models import ParsedQuote, QuoteLine, PriceBreak

# ── Number / currency parsing ───────────────────────────────────────────────

_CURRENCY_SYMBOLS = {
    "$": "USD", "US$": "USD", "usd": "USD",
    "€": "EUR", "eur": "EUR",
    "£": "GBP", "gbp": "GBP",
    "chf": "CHF", "¥": "JPY", "jpy": "JPY",
}


def detect_currency(text: str) -> str:
    if not text:
        return ""
    low = text.lower()
    for token, code in _CURRENCY_SYMBOLS.items():
        if token in text or token in low:
            return code
    return ""


def parse_number(val) -> Optional[float]:
    """Parse a possibly money-formatted string into a float.

    Handles US ("1,234.56", "$1,234.56") and European ("1.234,56", "1 234,56")
    grouping/decimal conventions.  Returns ``None`` when there is no number.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)

    s = str(val).strip()
    if not s:
        return None
    # Strip currency symbols / codes and anything that is not part of a number.
    s = re.sub(r"[^0-9,.\-]", "", s)
    if s in ("", "-", ".", ","):
        return None

    has_comma = "," in s
    has_dot = "." in s
    if has_comma and has_dot:
        # The right-most separator is the decimal point.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")     # European
        else:
            s = s.replace(",", "")                        # US
    elif has_comma:
        # A lone comma: decimal if it looks like "12,50", else a thousands sep.
        if re.match(r"^-?\d{1,3}(,\d{3})+$", s):
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def clean_str(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


# ── Column classification ───────────────────────────────────────────────────

# Header keywords -> logical field.  Order matters (first match wins per cell).
_FIELD_PATTERNS = [
    # No trailing \b here: several alternatives end in '#', where a trailing
    # word boundary can never match (# is already a non-word character).
    ("part_number", r"(part\s*#|part\s*(?:no|num|number)|drawing\s*#|"
                    r"drawing\s*(?:no|num)|item\s*#|item\s*(?:no|num)|"
                    r"\bp/?n\b|\bsku\b|\barticle\b|material\s*(?:no|number))"),
    ("description", r"\b(description|desc|designation|item\s*name|part\s*name)\b"),
    ("material",    r"\b(material|matl|grade|spec)\b"),
    ("moq",         r"\b(moq|min\.?\s*order|minimum\s*(order)?\s*qty)\b"),
    ("lead_time",   r"\b(lead\s*time|leadtime|delivery|\beta\b|weeks|days)\b"),
    ("tooling",     r"\b(tooling|tool\s*cost|nre|setup|set-?up)\b"),
    ("quantity",    r"\b(quantity|\bqty\b|volume|\beau\b|annual)\b"),
    ("unit_price",  r"\b(unit\s*price|unit\s*cost|price\s*(each|/?ea)?|cost|"
                    r"\brate\b|amount|\bp/u\b|price)\b"),
]

# A header cell that *is* a quantity break, e.g. "100", "Qty 500", "@1000",
# "1,000 pcs", "500 off".
_QTY_HEADER_RE = re.compile(
    r"^\s*(?:qty|quantity|@)?\s*"
    r"(\d[\d\s.,]*)\s*"
    r"(?:pcs?|pieces?|units?|ea|off|stk|stck)?\s*$",
    re.IGNORECASE,
)


def _qty_from_header(header: str) -> Optional[float]:
    """Return the quantity a column header encodes, else None."""
    if header is None:
        return None
    h = str(header).strip()
    if not h:
        return None
    m = _QTY_HEADER_RE.match(h)
    if not m:
        return None
    q = parse_number(m.group(1))
    # Guard against a stray part number being read as a quantity break.
    if q is None or q <= 0:
        return None
    return q


def classify_columns(header: Sequence) -> dict:
    """Map a header row to logical columns.

    Returns a dict with keys: ``fields`` (name -> col idx) and ``qty_cols``
    (col idx -> quantity value for wide-format price-break columns).
    """
    fields: dict = {}
    qty_cols: dict = {}
    for idx, cell in enumerate(header):
        text = clean_str(cell)
        if not text:
            continue
        qty = _qty_from_header(text)
        if qty is not None:
            qty_cols[idx] = qty
            continue
        low = text.lower()
        for name, pattern in _FIELD_PATTERNS:
            if name in fields:
                continue
            if re.search(pattern, low):
                fields[name] = idx
                break
    return {"fields": fields, "qty_cols": qty_cols}


def _looks_like_header(row: Sequence) -> bool:
    cls = classify_columns(row)
    f = cls["fields"]
    # A header needs some identity + at least one price/quantity signal.
    has_id = any(k in f for k in ("part_number", "description"))
    has_price = bool(cls["qty_cols"]) or "unit_price" in f or "quantity" in f
    return has_id and has_price


# ── Row -> QuoteLine assembly (shared by all formats) ───────────────────────

def _rows_to_lines(rows: List[List], warnings: List[str],
                   default_vendor: str = "") -> List[QuoteLine]:
    """Turn a list of raw rows (first usable header + data) into QuoteLines."""
    if not rows:
        return []

    # Locate the header row (best of the first 15 rows).
    header_idx = None
    for i, row in enumerate(rows[:15]):
        if _looks_like_header(row):
            header_idx = i
            break
    if header_idx is None:
        warnings.append("No recognizable header row (part/qty/price columns).")
        return []

    header = rows[header_idx]
    cls = classify_columns(header)
    fields, qty_cols = cls["fields"], cls["qty_cols"]
    data_rows = rows[header_idx + 1:]

    if qty_cols:
        return _parse_wide(data_rows, fields, qty_cols, default_vendor)
    if "quantity" in fields and "unit_price" in fields:
        return _parse_long(data_rows, fields, default_vendor, warnings)

    warnings.append("Header found but no quantity break or unit-price column.")
    return []


def _cell(row: Sequence, idx: Optional[int]):
    if idx is None or idx < 0 or idx >= len(row):
        return None
    return row[idx]


def _parse_wide(data_rows, fields, qty_cols, default_vendor) -> List[QuoteLine]:
    lines: List[QuoteLine] = []
    for row in data_rows:
        if not any(clean_str(c) for c in row):
            continue
        part = clean_str(_cell(row, fields.get("part_number")))
        desc = clean_str(_cell(row, fields.get("description")))
        if not part and not desc:
            continue
        breaks = []
        for col_idx, qty in sorted(qty_cols.items(), key=lambda kv: kv[1]):
            price = parse_number(_cell(row, col_idx))
            if price is not None and price > 0:
                breaks.append(PriceBreak(quantity=qty, unit_price=price))
        if not breaks:
            continue
        lines.append(QuoteLine(
            part_number=part or desc,
            description=desc,
            material=clean_str(_cell(row, fields.get("material"))),
            moq=parse_number(_cell(row, fields.get("moq"))),
            lead_time=clean_str(_cell(row, fields.get("lead_time"))),
            tooling=parse_number(_cell(row, fields.get("tooling"))),
            vendor=default_vendor,
            breaks=breaks,
        ))
    return lines


def _parse_long(data_rows, fields, default_vendor, warnings) -> List[QuoteLine]:
    """Long format: each row is one (quantity, unit_price) point.

    Rows are grouped by part number; if there is no part-number column every
    row belongs to a single implicit part.
    """
    grouped: dict = {}
    order: List[str] = []
    for row in data_rows:
        if not any(clean_str(c) for c in row):
            continue
        qty = parse_number(_cell(row, fields.get("quantity")))
        price = parse_number(_cell(row, fields.get("unit_price")))
        if qty is None or price is None or qty <= 0 or price <= 0:
            continue
        part = clean_str(_cell(row, fields.get("part_number"))) or "(quote)"
        if part not in grouped:
            grouped[part] = QuoteLine(
                part_number=part,
                description=clean_str(_cell(row, fields.get("description"))),
                material=clean_str(_cell(row, fields.get("material"))),
                vendor=default_vendor,
            )
            order.append(part)
        grouped[part].breaks.append(PriceBreak(quantity=qty, unit_price=price))
    return [grouped[p] for p in order]


# ── Vendor / currency inference from free text ──────────────────────────────

def _infer_vendor(texts: Sequence[str], filename: str) -> str:
    for t in texts:
        s = clean_str(t)
        m = re.match(r"(?:vendor|supplier|from|company)\s*[:\-]\s*(.+)", s, re.I)
        if m:
            return m.group(1).strip()[:80]
    # Fall back to the leading token of the filename.
    stem = Path(filename).stem
    token = re.split(r"[ _\-]", stem)[0]
    return token if token and not token.isdigit() else ""


def _infer_currency(texts: Sequence[str]) -> str:
    for t in texts:
        c = detect_currency(clean_str(t))
        if c:
            return c
    return ""


# ── Format-specific readers ─────────────────────────────────────────────────

def parse_excel(path: str) -> ParsedQuote:
    from openpyxl import load_workbook

    quote = ParsedQuote(source_type="xlsx", project=Path(path).stem)
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        quote.warnings.append(f"Could not open workbook: {exc}")
        return quote

    all_lines: List[QuoteLine] = []
    top_text: List[str] = []
    for ws in wb.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if not rows:
            continue
        top_text.extend(clean_str(c) for r in rows[:6] for c in r if c)
        all_lines.extend(_rows_to_lines(rows, quote.warnings))
    wb.close()

    quote.vendor = _infer_vendor(top_text, path)
    quote.currency = _infer_currency(top_text)
    for ln in all_lines:
        if not ln.vendor:
            ln.vendor = quote.vendor
    quote.lines = all_lines
    if not all_lines and not quote.warnings:
        quote.warnings.append("No quote lines detected in workbook.")
    return quote


def parse_csv(path: str) -> ParsedQuote:
    quote = ParsedQuote(source_type="csv", project=Path(path).stem)
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            rows = [list(r) for r in csv.reader(f, dialect)]
    except Exception as exc:  # noqa: BLE001
        quote.warnings.append(f"Could not read CSV: {exc}")
        return quote

    top_text = [c for r in rows[:6] for c in r if c]
    quote.vendor = _infer_vendor(top_text, path)
    quote.currency = _infer_currency(top_text)
    lines = _rows_to_lines(rows, quote.warnings, quote.vendor)
    quote.lines = lines
    if not lines and not quote.warnings:
        quote.warnings.append("No quote lines detected in CSV.")
    return quote


# Text-mode fallback for PDFs with no ruled tables: find qty/price pairs.
_TEXT_BREAK_RE = re.compile(
    r"(?:qty|quantity|@)?\s*(\d[\d.,]*)\s*"
    r"(?:pcs?|pieces?|units?|ea|off)?\s*[:\-]?\s*"
    r"[\$€£]?\s*(\d[\d.,]*\d|\d)\b",
    re.IGNORECASE,
)


def _parse_pdf_text(text: str, warnings: List[str]) -> List[QuoteLine]:
    breaks: List[PriceBreak] = []
    for line in text.splitlines():
        low = line.lower()
        if not any(k in low for k in ("price", "qty", "quantity", "each", "unit", "$", "€", "£")):
            continue
        for m in _TEXT_BREAK_RE.finditer(line):
            qty = parse_number(m.group(1))
            price = parse_number(m.group(2))
            if qty and price and qty > 0 and price > 0 and qty != price:
                breaks.append(PriceBreak(quantity=qty, unit_price=price))
    # De-duplicate on quantity, keep the lowest price seen.
    dedup: dict = {}
    for b in breaks:
        if b.quantity not in dedup or b.unit_price < dedup[b.quantity]:
            dedup[b.quantity] = b.unit_price
    if not dedup:
        return []
    warnings.append("PDF had no ruled table; extracted price breaks from text "
                    "(please double-check).")
    line = QuoteLine(part_number="(quote)",
                     breaks=[PriceBreak(q, p) for q, p in sorted(dedup.items())])
    return [line]


def parse_pdf(path: str) -> ParsedQuote:
    import pdfplumber

    quote = ParsedQuote(source_type="pdf", project=Path(path).stem)
    all_lines: List[QuoteLine] = []
    full_text_parts: List[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                full_text_parts.append(page_text)
                for table in page.extract_tables() or []:
                    rows = [[clean_str(c) for c in row] for row in table if row]
                    all_lines.extend(_rows_to_lines(rows, quote.warnings))
    except Exception as exc:  # noqa: BLE001
        quote.warnings.append(f"Could not read PDF: {exc}")
        return quote

    full_text = "\n".join(full_text_parts)
    if not all_lines:
        all_lines = _parse_pdf_text(full_text, quote.warnings)

    header_lines = full_text.splitlines()[:12]
    quote.vendor = _infer_vendor(header_lines, path)
    quote.currency = _infer_currency([full_text])
    for ln in all_lines:
        if not ln.vendor:
            ln.vendor = quote.vendor
    quote.lines = all_lines
    if not all_lines and not quote.warnings:
        quote.warnings.append("No tables or price breaks found in PDF.")
    return quote


# ── Public entry point ──────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xlsm", ".xltx", ".csv", ".tsv", ".txt"}


def parse_file(path: str) -> ParsedQuote:
    """Parse any supported file, dispatching on extension."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return parse_pdf(path)
    if ext in (".xlsx", ".xlsm", ".xltx"):
        return parse_excel(path)
    if ext in (".csv", ".tsv", ".txt"):
        return parse_csv(path)
    q = ParsedQuote(source_type=ext.lstrip("."), project=Path(path).stem)
    q.warnings.append(f"Unsupported file type: {ext}")
    return q

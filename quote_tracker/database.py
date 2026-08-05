"""
SQLite persistence for the Quote Tracker.

Schema (flexible quantity model - any set of quantity breaks, not a fixed list):

    quote_files   one row per imported file
    quote_lines   one row per part on a file
    price_breaks  one row per (quantity, unit_price) point on a line

The database file lives next to the executable / script by default so it can sit
in a shared OneDrive folder, exactly like the original tool.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import ParsedQuote, QuoteLine

# How long original quote files are kept before being purged from the database.
ORIGINAL_RETENTION_DAYS = 183   # ~6 months


def lead_time_weeks(text: str) -> Optional[float]:
    """Convert a free-text lead time to a comparable number of weeks.

    "4-6 weeks" -> 5.0 (midpoint), "10 to 11 Weeks" -> 10.5, "30 days" -> ~4.3,
    "8 wks" -> 8.0.  Returns None when no number can be found, so unknown lead
    times never win a "fastest delivery" comparison.
    """
    if not text:
        return None
    low = text.lower()
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", low)]
    if not nums:
        return None
    value = sum(nums[:2]) / len(nums[:2])   # midpoint of a range, else the value
    if "day" in low and "week" not in low and "wk" not in low:
        value /= 7.0
    elif "month" in low:
        value *= 4.345
    return round(value, 2)


class QuoteDB:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        self._init_schema()

    # ── connection helpers ──────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS quote_files (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename    TEXT NOT NULL,
                    source_type TEXT,
                    vendor      TEXT,
                    quote_number TEXT,
                    project     TEXT,
                    currency    TEXT,
                    file_hash   TEXT UNIQUE,
                    line_count  INTEGER DEFAULT 0,
                    loaded_at   TEXT DEFAULT (datetime('now','localtime')),
                    notes       TEXT
                );

                CREATE TABLE IF NOT EXISTS quote_lines (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id     INTEGER REFERENCES quote_files(id) ON DELETE CASCADE,
                    vendor      TEXT,
                    quote_number TEXT,
                    project     TEXT,
                    part_number TEXT,
                    description TEXT,
                    material    TEXT,
                    moq         REAL,
                    lead_time   TEXT,
                    tooling     REAL,
                    currency    TEXT,
                    notes       TEXT,
                    created_at  TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE TABLE IF NOT EXISTS price_breaks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    line_id     INTEGER REFERENCES quote_lines(id) ON DELETE CASCADE,
                    quantity    REAL NOT NULL,
                    unit_price  REAL NOT NULL
                );

                -- Original uploaded file, kept so it can be re-downloaded.
                -- Auto-purged after ORIGINAL_RETENTION_DAYS (see purge_old_originals).
                CREATE TABLE IF NOT EXISTS quote_originals (
                    file_id     INTEGER PRIMARY KEY REFERENCES quote_files(id) ON DELETE CASCADE,
                    filename    TEXT,
                    content     BLOB,
                    byte_size   INTEGER,
                    stored_at   TEXT DEFAULT (datetime('now','localtime'))
                );

                CREATE INDEX IF NOT EXISTS idx_lines_part   ON quote_lines(part_number);
                CREATE INDEX IF NOT EXISTS idx_lines_vendor ON quote_lines(vendor);
                CREATE INDEX IF NOT EXISTS idx_lines_file   ON quote_lines(file_id);
                CREATE INDEX IF NOT EXISTS idx_breaks_line  ON price_breaks(line_id);
                CREATE INDEX IF NOT EXISTS idx_breaks_qty   ON price_breaks(quantity);
                """
            )
            # Migrate databases created before quote_number existed.
            for table in ("quote_files", "quote_lines"):
                cols = {r["name"] for r in
                        conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if "quote_number" not in cols:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN quote_number TEXT")

    # ── hashing / duplicate detection ───────────────────────────────────
    @staticmethod
    def file_hash(path: str) -> str:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def find_by_hash(self, file_hash: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT id, filename FROM quote_files WHERE file_hash = ?",
                (file_hash,),
            ).fetchone()

    # ── writes ──────────────────────────────────────────────────────────
    def save_quote(self, quote: ParsedQuote, filename: str,
                   file_hash: Optional[str] = None,
                   original_bytes: Optional[bytes] = None) -> int:
        """Persist a (possibly user-edited) ParsedQuote. Returns the file id.

        When ``original_bytes`` is given the source file is kept so it can be
        re-downloaded later (auto-purged after ORIGINAL_RETENTION_DAYS).
        """
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO quote_files
                       (filename, source_type, vendor, quote_number, project,
                        currency, file_hash, line_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (filename, quote.source_type, quote.vendor, quote.quote_number,
                 quote.project, quote.currency, file_hash, len(quote.lines)),
            )
            file_id = cur.lastrowid
            for ln in quote.lines:
                lcur = conn.execute(
                    """INSERT INTO quote_lines
                           (file_id, vendor, quote_number, project, part_number,
                            description, material, moq, lead_time, tooling,
                            currency, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (file_id, ln.vendor or quote.vendor,
                     ln.quote_number or quote.quote_number, quote.project,
                     ln.part_number, ln.description, ln.material, ln.moq,
                     ln.lead_time, ln.tooling, quote.currency, ln.notes),
                )
                line_id = lcur.lastrowid
                conn.executemany(
                    "INSERT INTO price_breaks (line_id, quantity, unit_price) "
                    "VALUES (?, ?, ?)",
                    [(line_id, b.quantity, b.unit_price) for b in ln.breaks],
                )
            if original_bytes is not None:
                conn.execute(
                    """INSERT INTO quote_originals
                           (file_id, filename, content, byte_size)
                       VALUES (?, ?, ?, ?)""",
                    (file_id, filename, sqlite3.Binary(original_bytes),
                     len(original_bytes)),
                )
        return file_id

    # ── original files (download / retention) ───────────────────────────
    def get_original(self, file_id: int) -> Optional[Tuple[str, bytes]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT filename, content FROM quote_originals WHERE file_id = ?",
                (file_id,),
            ).fetchone()
        if row is None or row["content"] is None:
            return None
        return row["filename"], bytes(row["content"])

    def purge_old_originals(self, days: int = ORIGINAL_RETENTION_DAYS) -> int:
        """Delete stored original files older than ``days``.  Quote data (the
        parsed lines) is kept - only the re-downloadable file is dropped."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM quote_originals "
                "WHERE stored_at < datetime('now','localtime', ?)",
                (f"-{int(days)} days",),
            )
            return cur.rowcount

    def save_as(self, dest_file: str) -> str:
        """Copy the whole database (incl. stored originals) to ``dest_file``
        using the SQLite backup API - safe even with WAL data pending."""
        Path(dest_file).parent.mkdir(parents=True, exist_ok=True)
        src = self._connect()
        try:
            dst = sqlite3.connect(str(dest_file))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return str(dest_file)

    def backup_to(self, dest_dir: str) -> str:
        """Copy the database to ``dest_dir`` with a timestamped name."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.save_as(str(Path(dest_dir) / f"hawe_quotes_backup_{stamp}.db"))

    def delete_file(self, file_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM quote_files WHERE id = ?", (file_id,))

    def delete_line(self, line_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM quote_lines WHERE id = ?", (line_id,))

    # Fields the edit dialog is allowed to change.
    EDITABLE_FIELDS = ("part_number", "vendor", "quote_number", "description",
                       "material", "moq", "lead_time", "tooling", "currency",
                       "notes")

    def update_line(self, line_id: int, values: Dict,
                    breaks: Optional[Dict[float, float]] = None) -> None:
        """Update a saved quote line, and optionally replace its price breaks.

        ``breaks`` maps quantity -> unit price; passing it replaces the whole
        set for that line (so an edit can add, change and remove breaks).
        """
        updates = {k: v for k, v in values.items() if k in self.EDITABLE_FIELDS}
        with self._connect() as conn:
            if updates:
                clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(f"UPDATE quote_lines SET {clause} WHERE id = ?",
                             list(updates.values()) + [line_id])
            if breaks is not None:
                conn.execute("DELETE FROM price_breaks WHERE line_id = ?",
                             (line_id,))
                conn.executemany(
                    "INSERT INTO price_breaks (line_id, quantity, unit_price) "
                    "VALUES (?, ?, ?)",
                    [(line_id, q, p) for q, p in sorted(breaks.items())
                     if q and p])

    def get_line(self, line_id: int) -> Optional[Dict]:
        """One saved line with its price breaks, for editing."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM quote_lines WHERE id = ?",
                               (line_id,)).fetchone()
            if row is None:
                return None
            data = dict(row)
            brks = conn.execute(
                "SELECT quantity, unit_price FROM price_breaks "
                "WHERE line_id = ? ORDER BY quantity", (line_id,)).fetchall()
        data["breaks"] = {b["quantity"]: b["unit_price"] for b in brks}
        return data

    def update_line_notes(self, line_id: int, notes: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE quote_lines SET notes = ? WHERE id = ?",
                         (notes, line_id))

    # ── reads ───────────────────────────────────────────────────────────
    def list_files(self) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """SELECT qf.*,
                          (qo.file_id IS NOT NULL) AS has_original,
                          qo.byte_size AS original_size
                   FROM quote_files qf
                   LEFT JOIN quote_originals qo ON qo.file_id = qf.id
                   ORDER BY qf.loaded_at DESC, qf.id DESC"""
            ).fetchall()

    def part_numbers(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT part_number FROM quote_lines "
                "WHERE part_number IS NOT NULL AND part_number <> '' "
                "ORDER BY part_number"
            ).fetchall()
        return [r["part_number"] for r in rows]

    def distinct_quantities(self) -> List[float]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT quantity FROM price_breaks ORDER BY quantity"
            ).fetchall()
        return [r["quantity"] for r in rows]

    def vendors(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT vendor FROM quote_lines "
                "WHERE vendor IS NOT NULL AND vendor <> '' ORDER BY vendor"
            ).fetchall()
        return [r["vendor"] for r in rows]

    def kpis(self) -> Dict:
        with self._connect() as conn:
            def scalar(sql):
                return conn.execute(sql).fetchone()[0]
            return {
                "parts": scalar("SELECT COUNT(DISTINCT part_number) FROM quote_lines"),
                "vendors": scalar("SELECT COUNT(DISTINCT vendor) FROM quote_lines "
                                  "WHERE vendor IS NOT NULL AND vendor <> ''"),
                "lines": scalar("SELECT COUNT(*) FROM quote_lines"),
                "files": scalar("SELECT COUNT(*) FROM quote_files"),
                "best_price": scalar("SELECT MIN(unit_price) FROM price_breaks "
                                     "WHERE unit_price > 0"),
            }

    def quote_log(self, search: str = "", vendor: str = "",
                  part_number: str = "") -> List[Dict]:
        """Flat list of lines with their breaks folded into a dict."""
        sql = """
            SELECT ql.id, ql.vendor, ql.quote_number, ql.part_number,
                   ql.description, ql.material, ql.moq, ql.lead_time,
                   ql.tooling, ql.currency, ql.notes,
                   qf.filename, qf.loaded_at
            FROM quote_lines ql
            LEFT JOIN quote_files qf ON ql.file_id = qf.id
            WHERE 1=1
        """
        params: List = []
        if vendor:
            sql += " AND ql.vendor = ?"
            params.append(vendor)
        if part_number:
            sql += " AND ql.part_number = ?"
            params.append(part_number)
        if search:
            sql += (" AND (ql.part_number LIKE ? OR ql.description LIKE ? "
                    "OR ql.vendor LIKE ?)")
            like = f"%{search}%"
            params += [like, like, like]
        sql += " ORDER BY ql.part_number, ql.vendor"

        with self._connect() as conn:
            lines = [dict(r) for r in conn.execute(sql, params).fetchall()]
            for ln in lines:
                brks = conn.execute(
                    "SELECT quantity, unit_price FROM price_breaks "
                    "WHERE line_id = ? ORDER BY quantity", (ln["id"],)
                ).fetchall()
                ln["breaks"] = {b["quantity"]: b["unit_price"] for b in brks}
        return lines

    def comparison(self) -> List[Dict]:
        """Best (lowest) unit price per (part_number, quantity)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT ql.part_number, ql.description, ql.vendor,
                       pb.quantity, pb.unit_price
                FROM price_breaks pb
                JOIN quote_lines ql ON pb.line_id = ql.id
                ORDER BY ql.part_number, pb.quantity, pb.unit_price
                """
            ).fetchall()

        grouped: Dict[str, Dict] = {}
        for r in rows:
            part = r["part_number"] or "(unknown)"
            g = grouped.setdefault(part, {
                "part_number": part,
                "description": r["description"] or "",
                "vendors": set(),
                "best": {},          # qty -> (price, vendor)
            })
            if not g["description"] and r["description"]:
                g["description"] = r["description"]
            g["vendors"].add(r["vendor"])
            qty, price, vendor = r["quantity"], r["unit_price"], r["vendor"]
            if price and price > 0:
                if qty not in g["best"] or price < g["best"][qty][0]:
                    g["best"][qty] = (price, vendor)
        result = []
        for g in grouped.values():
            g["vendors"] = sorted(v for v in g["vendors"] if v)
            result.append(g)
        result.sort(key=lambda x: str(x["part_number"]))
        return result

    def study(self, part_number: str = "", vendor: str = "") -> List[Dict]:
        """Per-part supplier comparison for the decision study.

        Returns one group per part number, each with every supplier's price
        breaks, lead time and tooling.  Within a group it flags the lowest price
        at each quantity and the fastest lead time, so price-vs-delivery
        tradeoffs are visible at a glance.
        """
        sql = """
            SELECT ql.id, ql.part_number, ql.description, ql.vendor,
                   ql.quote_number, ql.material, ql.moq, ql.lead_time,
                   ql.tooling
            FROM quote_lines ql
            WHERE 1=1
        """
        params: List = []
        if part_number:
            sql += " AND ql.part_number = ?"
            params.append(part_number)
        if vendor:
            sql += " AND ql.vendor = ?"
            params.append(vendor)
        sql += " ORDER BY ql.part_number, ql.vendor"

        with self._connect() as conn:
            lines = [dict(r) for r in conn.execute(sql, params).fetchall()]
            for ln in lines:
                brks = conn.execute(
                    "SELECT quantity, unit_price FROM price_breaks "
                    "WHERE line_id = ? ORDER BY quantity", (ln["id"],)
                ).fetchall()
                ln["breaks"] = {b["quantity"]: b["unit_price"] for b in brks}
                ln["lead_weeks"] = lead_time_weeks(ln["lead_time"] or "")

        groups: Dict[str, Dict] = {}
        order: List[str] = []
        for ln in lines:
            part = ln["part_number"] or "(unknown)"
            if part not in groups:
                groups[part] = {"part_number": part,
                                "description": ln["description"] or "",
                                "suppliers": [],
                                "best_price": {},   # qty -> min price
                                "best_lead": None}
                order.append(part)
            g = groups[part]
            if not g["description"] and ln["description"]:
                g["description"] = ln["description"]
            g["suppliers"].append(ln)
            for qty, price in ln["breaks"].items():
                if price and price > 0:
                    if qty not in g["best_price"] or price < g["best_price"][qty]:
                        g["best_price"][qty] = price
            lw = ln["lead_weeks"]
            if lw is not None and (g["best_lead"] is None or lw < g["best_lead"]):
                g["best_lead"] = lw
        return [groups[p] for p in order]

    def export_rows(self) -> List[Dict]:
        return self.quote_log()

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
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from .models import ParsedQuote, QuoteLine


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

                CREATE INDEX IF NOT EXISTS idx_lines_part   ON quote_lines(part_number);
                CREATE INDEX IF NOT EXISTS idx_lines_vendor ON quote_lines(vendor);
                CREATE INDEX IF NOT EXISTS idx_lines_file   ON quote_lines(file_id);
                CREATE INDEX IF NOT EXISTS idx_breaks_line  ON price_breaks(line_id);
                CREATE INDEX IF NOT EXISTS idx_breaks_qty   ON price_breaks(quantity);
                """
            )

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
                   file_hash: Optional[str] = None) -> int:
        """Persist a (possibly user-edited) ParsedQuote. Returns the file id."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO quote_files
                       (filename, source_type, vendor, project, currency,
                        file_hash, line_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (filename, quote.source_type, quote.vendor, quote.project,
                 quote.currency, file_hash, len(quote.lines)),
            )
            file_id = cur.lastrowid
            for ln in quote.lines:
                lcur = conn.execute(
                    """INSERT INTO quote_lines
                           (file_id, vendor, project, part_number, description,
                            material, moq, lead_time, tooling, currency, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (file_id, ln.vendor or quote.vendor, quote.project,
                     ln.part_number, ln.description, ln.material, ln.moq,
                     ln.lead_time, ln.tooling, quote.currency, ln.notes),
                )
                line_id = lcur.lastrowid
                conn.executemany(
                    "INSERT INTO price_breaks (line_id, quantity, unit_price) "
                    "VALUES (?, ?, ?)",
                    [(line_id, b.quantity, b.unit_price) for b in ln.breaks],
                )
        return file_id

    def delete_file(self, file_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM quote_files WHERE id = ?", (file_id,))

    def delete_line(self, line_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM quote_lines WHERE id = ?", (line_id,))

    def update_line_notes(self, line_id: int, notes: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE quote_lines SET notes = ? WHERE id = ?",
                         (notes, line_id))

    # ── reads ───────────────────────────────────────────────────────────
    def list_files(self) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM quote_files ORDER BY loaded_at DESC, id DESC"
            ).fetchall()

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

    def quote_log(self, search: str = "", vendor: str = "") -> List[Dict]:
        """Flat list of lines with their breaks folded into a dict."""
        sql = """
            SELECT ql.id, ql.vendor, ql.part_number, ql.description, ql.material,
                   ql.moq, ql.lead_time, ql.tooling, ql.currency, ql.notes,
                   qf.filename, qf.loaded_at
            FROM quote_lines ql
            LEFT JOIN quote_files qf ON ql.file_id = qf.id
            WHERE 1=1
        """
        params: List = []
        if vendor:
            sql += " AND ql.vendor = ?"
            params.append(vendor)
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

    def export_rows(self) -> List[Dict]:
        return self.quote_log()

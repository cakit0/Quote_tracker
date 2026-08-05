"""
Data models for the Quote Tracker.

These are plain dataclasses shared between the parsers, the database layer and
the GUI.  Keeping them free of any Tkinter / SQLite imports means the whole
parsing + storage pipeline can be unit-tested head-less (no display required).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PriceBreak:
    """A single quantity -> unit price point on a quote line."""
    quantity: float
    unit_price: float


@dataclass
class QuoteLine:
    """One part / item on a supplier quote, with its quantity price breaks."""
    part_number: str = ""
    description: str = ""
    material: str = ""
    moq: Optional[float] = None
    lead_time: str = ""
    tooling: Optional[float] = None
    vendor: str = ""
    quote_number: str = ""
    notes: str = ""
    breaks: List[PriceBreak] = field(default_factory=list)

    def price_at(self, quantity: float) -> Optional[float]:
        for b in self.breaks:
            if b.quantity == quantity:
                return b.unit_price
        return None


@dataclass
class ParsedQuote:
    """The full result of parsing one file."""
    source_type: str = ""              # pdf / xlsx / csv
    vendor: str = ""
    quote_number: str = ""             # the supplier's own quote reference
    project: str = ""
    currency: str = ""
    lines: List[QuoteLine] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def quantities(self) -> List[float]:
        """Sorted list of every distinct quantity break found in the quote."""
        qs = {b.quantity for ln in self.lines for b in ln.breaks}
        return sorted(qs)

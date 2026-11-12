"""Source plugin 'gls': GLS Bank 'Umsaetze' CSV exports (wraps gls_parse.parse_gls_text)."""
from __future__ import annotations
from ....common import parsing
from ....common.types.bookings import BookingRow
from .. import gls_parse
from .base import head_text, register

_COLS = ("Bezeichnung Auftragskonto", "IBAN Auftragskonto", "Buchungstag", "Name Zahlungsbeteiligter", "Verwendungszweck", "Saldo nach Buchung")


class GlsPlugin:
    name = "gls"

    def detect(self, path: str, head: bytes) -> float:
        first = head_text(head).split("\n", 1)[0]
        if first.count(";") < 5:
            return 0.0
        hits = sum(c in first for c in _COLS)
        return 0.95 if hits >= 4 else 0.0

    def parse(self, path: str) -> list[BookingRow]:
        return gls_parse.parse_gls_text(parsing.read_text(path))


register(GlsPlugin())

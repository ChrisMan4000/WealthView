"""Source plugin 'paypal': PayPal activity exports ('Download*.CSV'). Its records are the raw csv rows (dicts keyed by the German column names)."""
from __future__ import annotations
import csv, io
from typing import Any
from ....common import parsing
from .. import gls_parse
from .base import head_text, register

NEED = ("Datum", "Transaktionscode")       # the columns an export must have (the same rule db_import has always used)


class PaypalPlugin:
    name = "paypal"

    def detect(self, path: str, head: bytes) -> float:
        first = head_text(head).split("\n", 1)[0]
        if not all(c in first for c in NEED):
            return 0.0
        return 0.95 if "Guthaben" in first else 0.85

    def parse(self, path: str) -> list[dict[str, Any]]:
        """All rows of the export. Raises gls_parse.UnsupportedFile when the header lacks the PayPal columns (callers decide how to report that)."""
        rd = csv.DictReader(io.StringIO(parsing.read_text(path)))
        if not rd.fieldnames or not all(c in rd.fieldnames for c in NEED):
            raise gls_parse.UnsupportedFile("not a PayPal activity export")
        return list(rd)


register(PaypalPlugin())

"""Source plugin 'gls_depot': GLS 'Depotbestand' exports (wraps gls_parse.parse_depot). Its records are positions, not bookings."""
from __future__ import annotations
import datetime as dt
import re
from ....common.types.depot import DepotMeta, ParsedPosition
from .. import gls_parse
from .base import head_text, register

_TABLE_HEADER = re.compile(r"^Name;\s*WKN", re.M)


class GlsDepotPlugin:
    name = "gls_depot"

    def detect(self, path: str, head: bytes) -> float:
        text = head_text(head)
        if not _TABLE_HEADER.search(text):
            return 0.0
        return 0.95 if "Depotbestand" in text else 0.7

    def parse_export(self, path: str) -> tuple[dt.date | None, list[ParsedPosition], DepotMeta]:
        """(export date or None, positions, total lines) - what db_import needs; raises gls_parse.UnsupportedFile without a table header."""
        return gls_parse.parse_depot(path)

    def parse(self, path: str) -> list[ParsedPosition]:
        return self.parse_export(path)[1]


register(GlsDepotPlugin())

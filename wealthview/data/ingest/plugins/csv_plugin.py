"""Source plugin 'csv': any bank CSV via the generic importer. Deliberately low confidence (<= 0.3 < MIN_CONFIDENCE): detect_best() never picks it,
so it cannot take a file from gls/paypal; a caller that knows the file is generic (a SourceSpec of kind 'csv') uses REGISTRY['csv'] directly.
Mapping channel: plugins only get a path, so the caller stores SourceSpec.mapping with set_mapping(path, mapping) before parse(path); without one the header names are guessed."""
from __future__ import annotations
import csv, io, os
from typing import Any
from .. import csv_generic, gls_parse
from .base import head_text, register

_MAPPINGS: dict[str, dict[str, Any]] = {}
CONF_SHAPE, CONF_MAPPED = 0.2, 0.3


def _key(path: str) -> str:
    return os.path.abspath(path)


def set_mapping(path: str, mapping: dict[str, Any]) -> None:
    """Remember the column mapping (SourceSpec.mapping) parse(path) should use."""
    _MAPPINGS[_key(path)] = dict(mapping)


def clear_mappings() -> None:
    _MAPPINGS.clear()


class CsvPlugin:
    name = "csv"

    def detect(self, path: str, head: bytes) -> float:
        """Header-only check (no IO): 0.3 when a mapping is stored and the head looks like delimited text, 0.2 when the header names look like a bank CSV."""
        text = head_text(head)
        first = text.split("\n", 1)[0].strip("\r")
        if not first:
            return 0.0
        d = max(csv_generic.DELIMITERS, key=first.count)
        if first.count(d) < 2:
            return 0.0
        if _key(path) in _MAPPINGS:
            return CONF_MAPPED
        cols = next(csv.reader(io.StringIO(first), delimiter=d), [])
        return CONF_SHAPE if csv_generic.guess_mapping(cols) else 0.0

    def parse(self, path: str, mapping: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Rows {date, amount, text, counterparty}. Mapping order: the explicit `mapping` argument, then the one stored with set_mapping(path), then a guess from the
        header. Stored mappings are per-process state: the caller must set_mapping() right before parsing (and may clear_mappings() afterwards); prefer the argument.
        Raises gls_parse.UnsupportedFile when no mapping is available or the mapping does not fit the file (message kept)."""
        mapping = mapping or _MAPPINGS.get(_key(path)) or csv_generic.guess_mapping(csv_generic.sniff(path).columns)
        if not mapping:
            raise gls_parse.UnsupportedFile("no column mapping for this CSV")
        try:
            return csv_generic.parse_with_mapping(path, mapping)
        except ValueError as exc:
            raise gls_parse.UnsupportedFile(str(exc)) from exc


register(CsvPlugin())

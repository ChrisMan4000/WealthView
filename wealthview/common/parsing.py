"""WealthView - small parsing helpers: German numbers and dates, text files in unknown encodings, rounding."""
from __future__ import annotations
from typing import overload
import datetime as dt
import re
from pathlib import Path
from . import safenet


def read_text(p: str | Path) -> str:
    """Text of a file; tries UTF-8 (with BOM), then Windows-1252, then Latin-1."""
    raw = Path(p).read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError as exc:      # wrong guess: try the next encoding
            safenet.swallowed("parsing.read_text", exc)
    return raw.decode("latin-1")


def num(s: str | None) -> float | None:
    """A German number like '1.234,56 EUR' as a float; None when there is no number."""
    if s is None:
        return None
    s = re.sub(r"[^0-9,.\-]", "", str(s))
    if s in ("", "-", ".", ","):
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def pdate(s: str | None) -> dt.date | None:
    """A 'dd.mm.yyyy' text as a date; None when it is not one."""
    try:
        return dt.datetime.strptime((s or "").strip(), "%d.%m.%Y").date()
    except ValueError:                # not a dd.mm.yyyy date: callers treat None as 'no date'
        return None


def iso(d: dt.date | None) -> str | None:
    """ISO text of a date (None stays None)."""
    return d.isoformat() if d else None


@overload
def round2(x: None) -> None: ...
@overload
def round2(x: float | int | str) -> float: ...
def round2(x: float | int | str | None) -> float | None:
    """Rounded to 2 decimals (None stays None)."""
    return None if x is None else round(float(x), 2)

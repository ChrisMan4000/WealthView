"""
WealthView - GLS file parsers (pure: text in, records out; no config, no network, no status reporting).
booking_label / kind_of / file_name_date / parse_gls_text read the bank CSV; parse_depot / depot_file_date read the depot export.
Used by loaders.py (which finds and caches the files), db_import.py (import into the database) and bookings.py.
"""
from __future__ import annotations
import csv, io
import datetime as dt
import re
from pathlib import Path
from ...common.parsing import num, pdate, read_text
from ...common.timeutil import NO_DATE, safe_date
from ...common.types.bookings import BookingRow, Kind
from ...common.types.depot import DepotMeta, ParsedPosition

class UnsupportedFile(ValueError):
    """The file is readable but is not an export we understand (it is remembered as skipped; other errors are retried next time)."""


# ------------------------------------------------------------- GLS Bank CSV
def booking_label(r: BookingRow) -> str:
    """A short readable name for a booking."""
    p = r["purpose"]
    ty = r["typ"].lower()
    if ty.startswith("kartenzahlung"):
        return (p.split("/")[0].strip() or "Card payment")[:34]
    if ty.startswith("auszahlung"):
        return "Cash withdrawal"
    m = re.search(r"Ihr Einkauf bei\s+(?!EREF)(.+?)(?:\s+EREF|\s*$)", p)
    if m:
        return m.group(1).strip()[:34]
    if "paypal" in r["counterparty"].lower():
        return "PayPal"
    if r["kind"] == "card":
        t = re.split(r"\s{2,}", p.strip())[0]
        t = re.sub(r"^(UZR\*|Vielen Dank,)\s*", "", t).strip()
        return (t or "Card")[:34]
    if r["counterparty"]:
        return r["counterparty"][:34]
    return (r["typ"] or "Booking")[:34]


def kind_of(name: str) -> Kind:
    n = name.lower()
    if "tagesgeld" in n:
        return "tages"
    if "kredit" in n:
        return "card"
    if "anteil" in n:
        return "shares"
    return "giro"


def file_name_date(p: str | Path) -> dt.date:
    """The last yyyy.mm.dd date in a file name (1970-01-01 when there is none or it is not a real day)."""
    m = re.findall(r"(\d{4})\.(\d{2})\.(\d{2})", Path(p).name)
    if m:
        y, mo, d = m[-1]
        return safe_date(y, mo, d)
    return NO_DATE


def parse_gls_text(text: str) -> list[BookingRow]:
    """Rows of one GLS 'Umsaetze' CSV. The only place that knows the GLS column names (db_import.py reuses it)."""
    out: list[BookingRow] = []
    for r in csv.DictReader(io.StringIO(text), delimiter=";"):
        date, amt = pdate(r.get("Buchungstag")), num(r.get("Betrag"))
        if not date or amt is None:
            continue
        acct = (r.get("Bezeichnung Auftragskonto") or "").strip()
        out.append(BookingRow(
            iban=(r.get("IBAN Auftragskonto") or "").strip(), account=acct, date=date,
            counterparty=(r.get("Name Zahlungsbeteiligter") or "").strip(),
            cp_iban=(r.get("IBAN Zahlungsbeteiligter") or "").strip(),
            typ=(r.get("Buchungstext") or "").strip(), purpose=(r.get("Verwendungszweck") or "").strip(),
            amount=amt, balance=num(r.get("Saldo nach Buchung")), cat=(r.get("Kategorie") or "").strip(),
            kind=kind_of(acct)))
    return out


# -------------------------------------------------------------- GLS depot
def parse_depot(path: str | Path) -> tuple[dt.date | None, list[ParsedPosition], DepotMeta]:
    """(export date or None when the header date is invalid, positions, total lines). Raises UnsupportedFile without a table header."""
    lines = read_text(path).splitlines()
    head = "\n".join(lines[:8])
    m = re.search(r"(\d{2}\.\d{2}\.\d{4})/(\d{2}:\d{2})", head)
    asof = pdate(m.group(1)) if m else _name_date_or_none(Path(path))
    hdr = next((i for i, l in enumerate(lines) if re.match(r"Name;\s*WKN", l)), None)      # older exports have a blank after each ;
    if hdr is None:
        raise UnsupportedFile("no table header")
    meta: DepotMeta = {}
    pos: list[ParsedPosition] = []
    for l in lines[hdr + 1:]:
        if not l.strip():
            continue
        c = [x.strip() for x in l.split(";")]
        second = c[1] if len(c) > 1 else ""       # a total line without a value gives None
        if c[0].startswith("Gesamtkurswert"):
            meta["total"] = num(second); continue
        if c[0].startswith("Kursgewinn/-verlust in EUR"):
            meta["gain"] = num(second); continue
        if c[0].startswith("Kursgewinn/-verlust in %"):
            meta["gain_pct"] = num(second); continue
        if len(c) >= 8 and c[1]:
            pos.append(ParsedPosition(raw=c[0], wkn=c[1], qty=num(c[2]), price=num(c[4]), value=num(c[5]),
                                      gain_pct=num(c[6]), gain=num(c[7])))
    return asof, pos, meta


def _name_date_or_none(p: Path) -> dt.date | None:
    """Fallback export date from the file name: d.m.yyyy (depot files) or yyyy.mm.dd; None when neither is a real day."""
    for d in (depot_file_date(p), file_name_date(p)):
        if d != NO_DATE:
            return d
    return None


def depot_file_date(p: str | Path) -> dt.date:
    """The export date in a Depotbestand_<d.m.yyyy>.csv file name (1970-01-01 when the name has none or it is not a real day)."""
    m = re.search(r"_(\d{1,2})\.(\d{1,2})\.(\d{4})\.csv$", Path(p).name, re.I)
    if m:
        return safe_date(m.group(3), m.group(2), m.group(1))
    return NO_DATE

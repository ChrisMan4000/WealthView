"""Generic CSV importer: sniff() guesses the shape of a bank CSV (encoding, delimiter, decimal mark, date format, columns, a few sample rows);
parse_with_mapping() turns the file into {date ISO, amount float, text, counterparty} rows using a column mapping (stored per bank in SourceSpec.mapping).
stdlib csv only. sniff() reads at most SNIFF_BYTES; parse streams the file. Bad rows are skipped and counted, never raised."""
from __future__ import annotations
import csv, re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SNIFF_BYTES = 65536
DELIMITERS = (";", ",", "\t", "|")
SAMPLE_ROWS = 5
DMY, MDY, ISO, DOTTED, DOTTED2 = "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"
_RE_DOTTED = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_RE_DOTTED2 = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2})$")       # two-digit year: yy < 70 -> 20yy, else 19yy
_RE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RE_SLASH = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_RE_NUM = re.compile(r"^[+-]?\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d+)?$|^[+-]?\d+(?:[.,]\d+)?$")


@dataclass
class CsvShape:
    """encoding: 'utf-8-sig' (BOM), 'utf-8' or 'cp1252'. decimal: ',' (1.234,56) or '.' (1,234.56). date_format: the dominant strptime format, '' when only
    ambiguous dd/mm vs mm/dd dates were seen. slash_format: the resolved format for a/b/yyyy dates, '' when ambiguous."""
    encoding: str = "utf-8"
    delimiter: str = ";"
    decimal: str = ","
    date_format: str = ""
    columns: list[str] = field(default_factory=list)
    sample: list[list[str]] = field(default_factory=list)
    slash_format: str = ""


def _decode(raw: bytes, truncated: bool) -> tuple[str, str]:
    """(text, encoding): utf-8-sig -> utf-8 -> cp1252. A multi-byte character cut by the head limit does not make the file non-UTF-8."""
    if raw[:3] == b"\xef\xbb\xbf":
        enc = "utf-8-sig"
    else:
        enc = "utf-8"
    for cut in ((0, 1, 2, 3) if truncated else (0,)):
        try:
            return (raw[:len(raw) - cut] if cut else raw).decode("utf-8-sig"), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1252", errors="replace"), "cp1252"


def _read_rows(text: str, delim: str, limit: int) -> list[list[str]]:
    out: list[list[str]] = []
    for row in csv.reader(text.splitlines(), delimiter=delim):
        if any(c.strip() for c in row):
            out.append([c.strip() for c in row])
            if len(out) >= limit:
                break
    return out


def _sniff_delimiter(text: str) -> str:
    best, best_score = ";", (0, 0)
    for d in DELIMITERS:
        rows = _read_rows(text, d, 10)
        counts = [len(r) for r in rows]
        if not counts:
            continue
        modal = max(set(counts), key=lambda n: (counts.count(n), n))
        score = (counts.count(modal) if modal > 1 else 0, modal)
        if score > best_score:
            best, best_score = d, score
    return best


def _sniff_decimal(cells: list[str], delim: str) -> str:
    votes = {",": 0, ".": 0}
    for c in cells:
        c = c.strip()
        if not _RE_NUM.match(c) or _RE_DOTTED.match(c):
            continue
        digits = re.sub(r"^[+-]", "", c)
        last = max(digits.rfind(","), digits.rfind("."))
        if last < 0:
            continue
        mark, tail = digits[last], digits[last + 1:]
        other = "." if mark == "," else ","
        if other in digits[:last] or " " in digits[:last] or len(tail) != 3:
            votes[mark] += 2
        else:
            votes[mark] += 0      # 1.234 / 1,234: could be either
    if votes[","] != votes["."]:
        return "," if votes[","] > votes["."] else "."
    return "," if delim != "," else "."


def _slash_format(cells: list[str]) -> str:
    first_gt12 = second_gt12 = False
    for c in cells:
        m = _RE_SLASH.match(c.strip())
        if m:
            first_gt12 |= int(m.group(1)) > 12
            second_gt12 |= int(m.group(2)) > 12
    if first_gt12 and not second_gt12:
        return DMY
    if second_gt12 and not first_gt12:
        return MDY
    return ""


def sniff(path: str) -> CsvShape:
    """Shape of the file from its first SNIFF_BYTES. Empty or unreadable file -> a CsvShape with no columns."""
    try:
        with open(path, "rb") as f:
            raw = f.read(SNIFF_BYTES + 1)
    except OSError:
        return CsvShape()
    truncated = len(raw) > SNIFF_BYTES
    raw = raw[:SNIFF_BYTES]
    text, enc = _decode(raw, truncated)
    text = text.lstrip("﻿")
    if truncated and "\n" in text:
        text = text[:text.rfind("\n")]        # drop the line cut by the head limit
    if not text.strip():
        return CsvShape(encoding=enc)
    delim = _sniff_delimiter(text)
    rows = _read_rows(text, delim, SAMPLE_ROWS * 4 + 1)
    columns, body = rows[0], rows[1:]
    cells = [c for r in body for c in r]
    counts = {DOTTED: 0, ISO: 0, DOTTED2: 0}
    for c in cells:
        counts[DOTTED] += bool(_RE_DOTTED.match(c))
        counts[ISO] += bool(_RE_ISO.match(c))
        counts[DOTTED2] += bool(_RE_DOTTED2.match(c))
    slash = _slash_format(cells)
    n_slash = sum(bool(_RE_SLASH.match(c)) for c in cells)
    if slash:
        counts[slash] = n_slash
    best = max(counts, key=lambda k: counts[k])
    return CsvShape(enc, delim, _sniff_decimal(cells, delim), best if counts[best] else "", columns, body[:SAMPLE_ROWS], slash)


def parse_date(s: str, slash_format: str = "") -> str | None:
    """ISO date of 'dd.mm.yyyy', 'yyyy-mm-dd' (a time part is dropped) or 'a/b/yyyy' (slash_format says which is the day); None when unparseable/ambiguous."""
    s = s.strip().replace("T", " ").split(" ")[0] if s.strip() else ""
    m2 = _RE_DOTTED2.match(s)
    if m2:
        yy = int(m2.group(3))
        s, fmt0 = f"{m2.group(1)}.{m2.group(2)}.{(2000 if yy < 70 else 1900) + yy}", DOTTED
        return _strptime(s, fmt0)
    for rx, fmt in ((_RE_DOTTED, DOTTED), (_RE_ISO, ISO), (_RE_SLASH, slash_format)):
        if rx.match(s):
            if not fmt:
                return None
            return _strptime(s, fmt)
    return None


def _strptime(s: str, fmt: str) -> str | None:
    try:
        return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_amount(s: str, decimal: str) -> float | None:
    """'1.234,56' (decimal ',') or '1,234.56' (decimal '.') as float; currency signs and spaces are ignored; None when not a number."""
    t = re.sub(r"[^\d.,+-]", "", s.replace(" ", " "))
    if not t:
        return None
    if t.endswith("-") and not t.startswith(("-", "+")):
        t = "-" + t[:-1]      # trailing minus: 12,50-
    t = t.replace(".", "").replace(",", ".") if decimal == "," else t.replace(",", "")
    if not re.match(r"^[+-]?(\d+\.?\d*|\.\d+)$", t):
        return None
    return float(t)


def _col(columns: list[str], name: str) -> int:
    """Index of the mapped column: exact name first, then case-insensitive. With duplicate header names the first one is used."""
    if name in columns:
        return columns.index(name)
    low = [c.strip().lower() for c in columns]
    if name.strip().lower() in low:
        return low.index(name.strip().lower())
    raise ValueError(f"column {name!r} not found in {columns}")


def _header(path: str, shape: CsvShape, delim: str) -> list[str]:
    """Header row read with an overridden delimiter (the sniffed columns belong to the sniffed delimiter)."""
    with open(path, encoding="utf-8-sig" if shape.encoding == "utf-8" else shape.encoding, errors="replace", newline="") as f:
        for row in csv.reader(f, delimiter=delim):
            if any(c.strip() for c in row):
                return [c.strip() for c in row]
    return []


def parse_with_mapping_stats(path: str, mapping: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """(rows, skipped). mapping: date + (amount | debit and/or credit) are required, text and counterparty optional; values are header names.
    Optional overrides: date_format (strptime format for a/b/yyyy dates), delimiter, decimal, encoding. Debit counts negative, credit positive.
    Raises ValueError for a mapped column the header lacks; rows that do not parse are skipped and counted."""
    shape = sniff(path)
    if not shape.columns:
        return [], 0
    if mapping.get("delimiter") and mapping["delimiter"] != shape.delimiter:
        shape.columns = _header(path, shape, mapping["delimiter"])
    delim, dec = mapping.get("delimiter") or shape.delimiter, mapping.get("decimal") or shape.decimal
    enc = mapping.get("encoding") or shape.encoding
    slash = mapping.get("date_format") or shape.slash_format
    if not mapping.get("date") or not (mapping.get("amount") or mapping.get("debit") or mapping.get("credit")):
        raise ValueError("mapping needs 'date' and 'amount' (or 'debit'/'credit')")
    idx = {k: _col(shape.columns, mapping[k]) for k in ("date", "amount", "text", "counterparty", "debit", "credit") if mapping.get(k)}
    out: list[dict[str, Any]] = []
    skipped = 0
    with open(path, encoding="utf-8-sig" if enc == "utf-8" else enc, errors="replace", newline="") as f:
        rd = csv.reader(f, delimiter=delim)
        for header in rd:
            if any(c.strip() for c in header):
                break
        for row in rd:
            if not any(c.strip() for c in row):
                continue
            def get(k: str, row: list[str] = row) -> str:
                return row[idx[k]].strip() if k in idx and idx[k] < len(row) else ""      # a short row has "" for missing cells
            try:
                date = parse_date(get("date"), slash)
                if "amount" in idx:
                    amount = parse_amount(get("amount"), dec)
                else:
                    d, c = get("debit"), get("credit")
                    dv, cv = parse_amount(d, dec) if d else 0.0, parse_amount(c, dec) if c else 0.0
                    amount = None if dv is None or cv is None or not (d or c) else cv - abs(dv)
                if date is None or amount is None:
                    raise ValueError("unparseable row")
            except ValueError:
                skipped += 1
                continue
            out.append({"date": date, "amount": amount, "text": get("text"), "counterparty": get("counterparty")})
    return out, skipped


def parse_with_mapping(path: str, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows of parse_with_mapping_stats() without the skipped count."""
    return parse_with_mapping_stats(path, mapping)[0]


_GUESS = {
    "date": ("buchungstag", "buchungsdatum", "datum", "date", "valuta", "booking date"),
    "amount": ("betrag", "amount", "umsatz", "value"),
    "debit": ("soll", "debit", "belastung"),
    "credit": ("haben", "credit", "gutschrift"),
    "text": ("verwendungszweck", "text", "description", "memo", "buchungstext", "reference"),
    "counterparty": ("empfaenger", "empfänger", "auftraggeber", "name", "payee", "counterparty", "beguenstigter", "begünstigter"),
}


def guess_mapping(columns: list[str]) -> dict[str, str] | None:
    """Mapping guessed from common German/English header names; None unless a date and an amount (or debit/credit) column are found."""
    m: dict[str, str] = {}
    for key, names in _GUESS.items():
        for c in columns:
            if c.strip().lower() in names and c not in m.values():
                m[key] = c
                break
    if "date" not in m or not ("amount" in m or "debit" in m or "credit" in m):
        return None
    return m

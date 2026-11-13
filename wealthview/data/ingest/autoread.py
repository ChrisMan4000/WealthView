"""WealthView automatic reader (v1.20): works out by itself what an unknown CSV file is - a bank account, a credit card, a securities depot,
securities trades or crypto transactions - and reads it, with no preview and no column-matching screen.
How: sniff the text (encoding incl. UTF-16, delimiter, the header row after any preamble), type every column by its CONTENT (dates, numbers, ISIN,
IBAN, asset codes) and by multilingual header words, score each kind, then check the guess with proofs the file has to pass (a running balance that
adds up, quantity x price = value). A file that does not clearly fit any kind is "unknown": the caller asks the person one plain question.
Reads only; never writes. Standard library only."""
from __future__ import annotations
import csv, hashlib, io, re, unicodedata
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path
from typing import Any

from . import csv_generic

MAX_BYTES = 64 * 1024 * 1024
SAMPLE = 400                   # rows used to type a column
MIN_CONFIDENCE = 0.55          # below this the kind is "unknown"
KINDS = ("bank", "card", "depot", "trades", "crypto")
FIAT = {"EUR", "USD", "GBP", "CHF", "JPY", "CAD", "AUD"}
ASSET_ALIASES = {"XBT": "BTC", "XXBT": "BTC", "XETH": "ETH", "XXRP": "XRP", "XLTC": "LTC", "XXDG": "DOGE", "XDG": "DOGE"}

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")
_IBAN_FIND = re.compile(r"\b([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,4})?)\b")
_CODE = re.compile(r"^[A-Z][A-Z0-9]{1,5}(?:\.[A-Z])?$")
_NUM = re.compile(r"^[+-]?\s*[€$£]?\s*[+-]?\d[\d.,'  ]*\s*(?:[€$£]|EUR|USD|GBP|CHF)?\s*-?$")
_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")
_DATE_IN_TEXT = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})")
_NAME_DATE = re.compile(r"(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})|(\d{2})[-_.](\d{2})[-_.](\d{4})")
_SNAPSHOT_WORDS = ("stand", "as of", "asof", "per ", "datum", "date", "bestand", "valuation", "bewertung")


def _hn(s: str) -> str:
    """header normalised: lower case, accents removed, only words"""
    t = unicodedata.normalize("NFKD", s.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _words(*names: str) -> tuple[str, ...]:
    return tuple(_hn(n) for n in names)


W_DATE = _words("buchungstag", "buchungsdatum", "booking date", "transaction date", "trade date", "timestamp", "datum", "date", "time", "zeit", "fecha", "data",
                "date operation", "completed date", "handelstag", "ausfuhrungsdatum")
W_VALUTA = _words("valuta", "valutadatum", "value date", "wertstellung")
W_AMOUNT = _words("betrag", "amount", "umsatz", "montant", "importe", "bedrag", "sum", "betrag eur", "amount eur", "value eur")
W_DEBIT = _words("soll", "debit", "belastung", "debet", "ausgabe", "withdrawal amount", "paid out", "money out")
W_CREDIT = _words("haben", "credit", "gutschrift", "kredit", "einnahme", "paid in", "money in")
W_DIRECTION = _words("soll haben", "s h", "af bij", "debit credit", "dc", "cr dr")
W_BALANCE = _words("saldo", "kontostand", "balance", "solde", "saldo nach buchung", "running balance", "available balance", "saldo eur")
W_TEXT = _words("verwendungszweck", "text", "description", "memo", "buchungstext", "reference", "beschreibung", "details", "payment reference", "libelle",
                "concepto", "omschrijving", "note", "notes", "subject", "betreff", "zahlungsreferenz")
W_COUNTERPARTY = _words("empfanger", "auftraggeber", "name", "payee", "counterparty", "beguenstigter", "begunstigter", "merchant", "handler", "haendler",
                        "name zahlungsbeteiligter", "partner", "empfanger zahlungspflichtiger", "auftraggeber empfanger", "beneficiary", "vendor",
                        "beguenstigter zahlungspflichtiger", "name empfanger", "payer")
W_IBAN = _words("iban", "konto", "account number", "kontonummer", "account", "konto nr")
W_CARD = _words("card", "kartennummer", "kreditkarte", "karte", "kartenmummer", "card number", "cardholder", "karteninhaber", "merchant category")
W_ISIN = _words("isin")
W_WKN = _words("wkn", "symbol", "ticker", "security id", "valor")
W_SECNAME = _words("bezeichnung", "wertpapier", "security", "name", "instrument", "description", "produkt", "product", "titel", "fund name")
W_QTY = _words("stuck", "stueck", "anzahl", "menge", "quantity", "qty", "shares", "units", "nominal", "bestand", "position", "volume", "size",
               "quantity transacted", "stuck nominal")
W_PRICE = _words("kurs", "preis", "price", "kurs preis", "aktueller kurs", "last price", "current price", "unit price", "price per coin", "ausfuhrungskurs",
                 "spot price at transaction", "price eur", "kaufkurs")
W_VALUE = _words("wert", "marktwert", "kurswert", "value", "market value", "total value", "wert eur", "kurswert eur", "betrag eur", "total", "valuation")
W_COST = _words("einstandswert", "einstandskurs", "cost", "cost basis", "anschaffungswert", "book value", "buchwert", "kaufwert")
W_GAIN = _words("gewinn", "gewinn verlust", "gain", "profit", "p l", "pnl", "performance", "unrealised", "unrealized gain loss")
W_ASSET = _words("asset", "coin", "symbol", "token", "crypto", "cryptocurrency", "currency", "waehrung", "wahrung", "krypto", "pair", "market")
W_TYPE = _words("type", "transaction type", "transaktionstyp", "operation", "side", "action", "typ", "kind", "buy sell", "art", "transaktion", "order type")
W_TOTAL = _words("total inclusive of fees and or spread", "total", "subtotal", "fiat amount", "eur value", "total eur", "gesamt", "cost basis eur", "value eur",
                 "wert eur", "betrag eur", "proceeds", "total price")
W_FEE = _words("fee", "fees", "gebuhr", "gebuehr", "fees and or spread", "commission", "provision", "kosten")
W_CURRENCY = _words("waehrung", "wahrung", "currency", "devise", "moneda", "spot price currency", "price currency", "fiat", "quote currency")

_BUY, _SELL = ("buy", "purchase", "kauf", "bought", "acheter", "compra", "market buy", "limit buy", "advanced trade buy"), ("sell", "verkauf", "sold", "vente", "venta", "market sell", "limit sell", "advanced trade sell")
_IN = ("deposit", "receive", "received", "einzahlung", "eingang", "transfer in", "incoming", "credit", "eingehend", "ein")
_OUT = ("withdraw", "withdrawal", "send", "sent", "auszahlung", "ausgang", "transfer out", "outgoing", "debit", "ausgehend", "aus")
_REWARD = ("reward", "staking", "interest", "earn", "airdrop", "income", "payout", "dividend", "zinsen", "bonus", "learning")
_TRADE = ("trade", "convert", "swap", "exchange", "tausch", "spend")
_CARD_FILE = ("visa", "mastercard", "amex", "kreditkarte", "creditcard", "credit card", "card", "karte")


@dataclass
class Table:
    encoding: str
    delimiter: str
    columns: list[str]
    rows: list[list[str]]
    preamble: list[str] = field(default_factory=list)


@dataclass
class Analysis:
    """What the reader made of one file. kind: bank | card | depot | trades | crypto | unknown. cols maps a role (date, amount, debit ...) to a column index;
    mapping the same with the header text (for messages). confidence 0..1; reasons say in plain words what decided it."""
    kind: str = "unknown"
    confidence: float = 0.0
    cols: dict[str, int] = field(default_factory=dict)
    mapping: dict[str, str] = field(default_factory=dict)
    ident: str = ""                  # IBAN / card tail ('' = none found)
    currency: str = "EUR"
    asof: str | None = None          # depot snapshot date
    fingerprint: str = ""
    reasons: list[str] = field(default_factory=list)
    flip_sign: bool = False          # card file that lists purchases as positive numbers
    decimals: dict[int, str] = field(default_factory=dict)
    slashes: dict[int, str] = field(default_factory=dict)
    delimiter: str = ";"
    encoding: str = "utf-8"
    guess: str = ""                  # the best guess when kind is unknown (for the question), '' when none


# ------------------------------------------------------------------ reading
def _decode(raw: bytes) -> tuple[str, str] | None:
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace"), "utf-16"
    if b"\x00" in raw[:4096]:
        return None          # binary
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), "cp1252"


def _is_num(s: str) -> bool:
    return bool(s) and bool(_NUM.match(s.strip()))


def _pick_delimiter(text: str) -> str:
    best, score = ";", (0, 0)
    head = "\n".join(text.splitlines()[:120])
    for d in (";", ",", "\t", "|"):
        widths = [len(r) for r in csv.reader(io.StringIO(head), delimiter=d) if any(c.strip() for c in r)]
        wide = [w for w in widths if w >= 2]
        if not wide:
            continue
        modal = max(set(wide), key=lambda n: (wide.count(n), n))
        s = (wide.count(modal), modal)
        if s > score:
            best, score = d, s
    return best


def _header_like(row: list[str]) -> bool:
    cells = [c.strip() for c in row]
    filled = [c for c in cells if c]
    if len(filled) < max(2, int(len(cells) * 0.6)) or len(set(filled)) < len(filled) * 0.6:
        return False
    numish = sum(_is_num(c) or csv_generic.parse_date(c, csv_generic.MDY) is not None for c in filled)
    return numish <= len(filled) * 0.25


def read_table(path: str | Path, limit: int | None = None) -> Table | None:
    """The file as a Table (columns, data rows, preamble lines before the header); None for an unreadable, empty or binary file."""
    try:
        p = Path(path)
        if p.stat().st_size > MAX_BYTES:
            return None
        raw = p.read_bytes()
    except OSError:
        return None
    dec = _decode(raw)
    if dec is None or not dec[0].strip():
        return None
    text, enc = dec
    delim = _pick_delimiter(text)
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    wide = [len(r) for r in rows[:80] if len(r) >= 2]
    if not wide:
        return None
    width = max(set(wide), key=lambda n: (wide.count(n), n))
    head = next((i for i, r in enumerate(rows[:80]) if len(r) == width and _header_like(r) and i + 1 < len(rows) and len(rows[i + 1]) >= 2), None)
    if head is None:
        return None
    body = [r + [""] * (width - len(r)) if len(r) < width else r[:width] for r in rows[head + 1:] if len(r) >= 2]
    return Table(enc, delim, rows[head], body[:limit] if limit else body, [" ".join(r) for r in rows[:head]])


def fingerprint_of(columns: list[str], delimiter: str) -> str:
    return hashlib.sha1((delimiter + "|" + "|".join(_hn(c) for c in columns)).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


# ------------------------------------------------------------------ cells
def _parse_date_cell(s: str, slash: str = "") -> str | None:
    s = s.strip()
    if not s:
        return None
    m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})(?=$|[ T])", s)
    if m:
        s = f"{m.group(1)}.{m.group(2)}.{m.group(3)}" + s[m.end():]
    m = re.match(r"^(\d{4})/(\d{2})/(\d{2})(?=$|[ T])", s)
    if m:
        s = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" + s[m.end():]
    return csv_generic.parse_date(s, slash)


def _time_of(s: str) -> str:
    m = _TIME.search(s)
    return f"T{int(m.group(1)):02d}:{m.group(2)}:{int(m.group(3) or 0):02d}" if m else ""


def _num(s: str, dec: str) -> float | None:
    s = s.strip()
    return csv_generic.parse_amount(s, dec) if _is_num(s) else None


@dataclass
class _Col:
    idx: int
    name: str
    hn: str
    cells: list[str]
    date_frac: float = 0.0
    num_frac: float = 0.0
    isin_frac: float = 0.0
    iban_frac: float = 0.0
    code_frac: float = 0.0
    fiat_frac: float = 0.0
    distinct: int = 0
    slash: str = ""
    decimal: str = ","
    neg_frac: float = 0.0


def _profile(table: Table) -> list[_Col]:
    out = []
    for i, name in enumerate(table.columns):
        cells = [r[i] for r in table.rows[:SAMPLE] if r[i].strip()]
        c = _Col(i, name, _hn(name), cells)
        n = len(cells)
        if n:
            c.slash = csv_generic._slash_format(cells)
            c.date_frac = sum(_parse_date_cell(x, c.slash or csv_generic.DMY) is not None for x in cells) / n
            nums = [x for x in cells if _is_num(x)]
            c.num_frac = len(nums) / n
            if nums:
                c.decimal = csv_generic._sniff_decimal(nums, table.delimiter)
                vals = [csv_generic.parse_amount(x, c.decimal) for x in nums]
                c.neg_frac = sum(1 for v in vals if v is not None and v < 0) / len(nums)
            c.isin_frac = sum(bool(_ISIN.match(x.upper())) for x in cells) / n
            c.iban_frac = sum(bool(_IBAN.match(x.replace(" ", "").upper())) for x in cells) / n
            c.code_frac = sum(bool(_CODE.match(x)) for x in cells) / n
            c.fiat_frac = sum(x.upper() in FIAT for x in cells) / n
            c.distinct = len(set(cells))
        out.append(c)
    return out


def _find(cols: list[_Col], words: tuple[str, ...], used: set[int], need: str = "", exact_first: bool = True) -> _Col | None:
    """first column whose header equals one of the words (in the order of the words), else whose header contains one as whole words"""
    ok = [c for c in cols if c.idx not in used and c.cells and (need != "num" or c.num_frac >= 0.7) and (need != "numsoft" or c.num_frac >= 0.4) and (need != "date" or c.date_frac >= 0.7)
          and (need != "text" or c.num_frac < 0.5)]
    for w in words:
        for c in ok:
            if c.hn == w:
                return c
    for w in words:
        for c in ok:
            if f" {w} " in f" {c.hn} ":
                return c
    return None


# ------------------------------------------------------------------ analysis
def _ident_from(table: Table, path: str, cols: list[_Col], iban_col: _Col | None) -> str:
    if iban_col is not None and iban_col.cells:
        top = max(set(iban_col.cells), key=iban_col.cells.count)
        t = top.replace(" ", "").upper()
        if _IBAN.match(t):
            return t
    for line in table.preamble + [Path(path).stem]:
        m = _IBAN_FIND.search(line.upper())
        if m and _IBAN.match(m.group(1).replace(" ", "")):
            return m.group(1).replace(" ", "")
    return ""


def _asof_for(table: Table, path: str, datecol: _Col | None) -> tuple[str | None, str]:
    if datecol is not None and datecol.cells:
        ds = [d for d in (_parse_date_cell(x, datecol.slash or csv_generic.DMY) for x in datecol.cells) if d]
        if ds:
            return max(ds), "the date column"
    for line in table.preamble:
        low = line.lower()
        m = _DATE_IN_TEXT.search(line)
        if m and any(w in low for w in _SNAPSHOT_WORDS):
            d = _parse_date_cell(m.group(1), csv_generic.DMY)
            if d:
                return d, "the line above the table"
    m = _NAME_DATE.search(Path(path).stem)
    if m:
        try:
            yy, mm, dd = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m.group(1) else (int(m.group(6)), int(m.group(5)), int(m.group(4)))
            return _date(yy, mm, dd).isoformat(), "the file name"
        except ValueError:
            pass
    try:
        return _date.fromtimestamp(Path(path).stat().st_mtime).isoformat(), "the file's change time"
    except OSError:
        return None, ""


def _balance_proof(rows: list[tuple[float, float]]) -> bool:
    """rows = [(amount, balance)] in file order; True when the balance column adds up (oldest first or newest first)"""
    if len(rows) < 3:
        return False
    fwd = sum(abs(rows[i][1] - rows[i - 1][1] - rows[i][0]) < 0.015 for i in range(1, len(rows)))
    rev = sum(abs(rows[i - 1][1] - rows[i][1] - rows[i - 1][0]) < 0.015 for i in range(1, len(rows)))
    return max(fwd, rev) >= 0.9 * (len(rows) - 1)


def _sides(vals: list[str]) -> float:
    """share of cells that read like a buy / sell / transfer / reward"""
    if not vals:
        return 0.0
    keys = _BUY + _SELL + _IN + _OUT + _REWARD + _TRADE
    hit = sum(any(k in _hn(v).split() or k in _hn(v) for k in keys) for v in vals)
    return hit / len(vals)


def _score_depot(cols: list[_Col], table: Table, a: Analysis) -> float:
    used: set[int] = set()
    isin = next((c for c in cols if c.isin_frac >= 0.6), None) or _find(cols, W_ISIN, used)
    wkn = None if isin else _find(cols, W_WKN, used)
    if isin is None and wkn is None:
        return 0.0
    ident = isin or wkn
    assert ident is not None
    used.add(ident.idx)
    qty = _find(cols, W_QTY, used, "num")
    if qty:
        used.add(qty.idx)
    price = _find(cols, W_PRICE, used, "num")
    if price:
        used.add(price.idx)
    value = _find(cols, W_VALUE, used, "num")
    if value:
        used.add(value.idx)
    if qty is None or (price is None and value is None):
        return 0.0
    name = _find(cols, W_SECNAME, used, "text")
    a.cols.update({"id": ident.idx, "qty": qty.idx})
    for role, c in (("price", price), ("value", value), ("name", name)):
        if c:
            a.cols[role] = c.idx
    cost = _find(cols, W_COST, used, "num")
    gain = _find(cols, W_GAIN, used, "num")
    for role, c in (("cost", cost), ("gain", gain)):
        if c:
            a.cols[role] = c.idx
    s = 0.55 if isin is not None and isin.isin_frac >= 0.6 else 0.4
    s += 0.15 if qty.hn in W_QTY else 0.08
    s += 0.1 if (price or value) else 0
    if price and value:
        ok = tot = 0
        for r in table.rows[:SAMPLE]:
            q, p, v = _num(r[qty.idx], qty.decimal), _num(r[price.idx], price.decimal), _num(r[value.idx], value.decimal)
            if q is None or p is None or v is None:
                continue
            tot += 1
            ok += abs(q * p - v) <= max(0.02, abs(v) * 0.01)
        if tot >= 2 and ok >= 0.7 * tot:
            s += 0.2
            a.reasons.append("quantity x price = value for most rows")
    elif price or value:
        s += 0.05
    a.reasons.append("has security ids and quantities")
    return min(s, 1.0)


def _score_crypto(cols: list[_Col], table: Table, a: Analysis, path: str) -> float:
    used: set[int] = set()
    asset = next((c for c in _by_words(cols, W_ASSET, used) if c.code_frac >= 0.8 and c.fiat_frac < 0.9 and c.distinct <= 60), None)
    if asset is None:
        asset = next((c for c in cols if c.cells and c.code_frac >= 0.9 and c.fiat_frac < 0.5 and 1 <= c.distinct <= 40 and not c.num_frac
                      and any(w == c.hn for w in W_ASSET)), None)
    if asset is None:
        return 0.0
    used.add(asset.idx)
    typ = next((c for c in _by_words(cols, W_TYPE, used) if _sides(c.cells) >= 0.6), None)
    if typ:
        used.add(typ.idx)
    dcol = _find(cols, W_DATE, used, "date")
    if dcol is None:
        return 0.0
    used.add(dcol.idx)
    qty = _find(cols, W_QTY + W_AMOUNT, used, "num")
    if qty is None:
        return 0.0
    used.add(qty.idx)
    price = _find(cols, W_PRICE, used, "num")
    if price:
        used.add(price.idx)
    total = _find(cols, W_TOTAL, used, "num")
    if total:
        used.add(total.idx)
    fee = _find(cols, W_FEE, used, "num")
    cur = _find(cols, W_CURRENCY, used)
    a.cols.update({"asset": asset.idx, "date": dcol.idx, "qty": qty.idx})
    for role, c in (("type", typ), ("price", price), ("total", total), ("fee", fee), ("currency", cur)):
        if c and c.idx != asset.idx:
            a.cols[role] = c.idx
    s = 0.35 + (0.25 if typ else 0.0) + 0.15 + 0.1 + (0.1 if (price or total) else 0.0)
    if typ is None and not (price or total):
        s -= 0.2
    if any(w in _hn(c.name) for c in cols for w in ("spot price", "fees and or spread", "quantity transacted")):
        s += 0.05
    a.reasons.append("has asset codes with quantities" + (" and buy/sell words" if typ else ""))
    return min(s, 1.0)


def _by_words(cols: list[_Col], words: tuple[str, ...], used: set[int]) -> list[_Col]:
    out = []
    for w in words:
        for c in cols:
            if c.idx not in used and c.cells and (c.hn == w or f" {w} " in f" {c.hn} ") and c not in out:
                out.append(c)
    return out


def _score_bank(cols: list[_Col], table: Table, a: Analysis, path: str) -> tuple[float, bool]:
    used: set[int] = set()
    dcol = _find(cols, W_DATE, used, "date") or next((c for c in cols if c.date_frac >= 0.8), None)
    if dcol is None:
        return 0.0, False
    used.add(dcol.idx)
    val = _find(cols, W_VALUTA, used, "date")
    if val:
        used.add(val.idx)
    amount = _find(cols, W_AMOUNT, used, "num")
    debit = _find(cols, W_DEBIT, used, "numsoft")
    credit = _find(cols, W_CREDIT, used, "numsoft")
    if amount:
        used.add(amount.idx)
    if debit:
        used.add(debit.idx)
    if credit:
        used.add(credit.idx)
    direction = _find(cols, W_DIRECTION, used, "text")
    if amount is None and debit is None and credit is None:
        nums = [c for c in cols if c.idx not in used and c.num_frac >= 0.9 and c.cells and c.hn not in W_BALANCE and c.hn not in W_QTY]
        if len(nums) >= 1 and any(0.05 < c.neg_frac < 0.98 for c in nums):
            amount = next(c for c in nums if 0.05 < c.neg_frac < 0.98)      # a signed number column
            used.add(amount.idx)
            a.reasons.append("one signed number column")
    if amount is None and (debit is None or credit is None) and not (debit or credit):
        return 0.0, False
    bal = _find(cols, W_BALANCE, used, "num")
    if bal:
        used.add(bal.idx)
    iban = next((c for c in cols if c.iban_frac >= 0.8 and c.idx not in used), None) or _find(cols, W_IBAN, used)
    cp = _find(cols, W_COUNTERPARTY, used, "text")
    if cp:
        used.add(cp.idx)
    text = _find(cols, W_TEXT, used, "text")
    if text:
        used.add(text.idx)
    if text is None and cp is None:
        free = [c for c in cols if c.idx not in used and c.cells and c.num_frac < 0.3 and c.date_frac < 0.5]
        if free:
            text = max(free, key=lambda c: sum(len(x) for x in c.cells) / len(c.cells))
            used.add(text.idx)
    a.cols["date"] = dcol.idx
    for role, c in (("amount", amount), ("debit", debit), ("credit", credit), ("balance", bal), ("text", text), ("counterparty", cp), ("direction", direction),
                    ("iban", iban)):
        if c:
            a.cols[role] = c.idx
    s = 0.3 + (0.3 if (amount and amount.hn in W_AMOUNT) or (debit and credit) else 0.22)
    s += 0.15 if (text or cp) else 0.0
    if bal:
        pairs = []
        for r in table.rows[:SAMPLE]:
            amt = _row_amount(r, a, {i: c.decimal for i, c in enumerate(cols)})
            b = _num(r[bal.idx], bal.decimal)
            if amt is not None and b is not None:
                pairs.append((amt, b))
        if _balance_proof(pairs):
            s += 0.25
            a.reasons.append("the balance column adds up to the amounts")
        else:
            s += 0.05
    if iban:
        s += 0.05
    if dcol.hn in W_DATE:
        s += 0.05
    card_words = any(c.hn in W_CARD or any(f" {w} " in f" {c.hn} " for w in W_CARD) for c in cols)
    named_card = any(w in Path(path).stem.lower() for w in _CARD_FILE) or any(w in " ".join(table.preamble).lower() for w in ("kreditkarte", "credit card", "visa", "mastercard"))
    return min(s, 1.0), bool(card_words or named_card)


def _row_amount(r: list[str], a: Analysis, dec: dict[int, str]) -> float | None:
    cols = a.cols
    if "amount" in cols:
        v = _num(r[cols["amount"]], dec.get(cols["amount"], ","))
        if v is not None and "direction" in cols:
            d = _hn(r[cols["direction"]])
            if d in ("s", "soll", "debit", "af", "dr", "d", "db"):
                return -abs(v)
            if d in ("h", "haben", "credit", "bij", "cr", "c", "cd"):
                return abs(v)
        return -v if (v is not None and a.flip_sign) else v
    dv = _num(r[cols["debit"]], dec.get(cols["debit"], ",")) if "debit" in cols and r[cols["debit"]].strip() else 0.0
    cv = _num(r[cols["credit"]], dec.get(cols["credit"], ",")) if "credit" in cols and r[cols["credit"]].strip() else 0.0
    if dv is None or cv is None or not ((cols.get("debit") is not None and r[cols["debit"]].strip()) or (cols.get("credit") is not None and r[cols["credit"]].strip())):
        return None
    return cv - abs(dv)


def analyze(path: str | Path, force: str | None = None) -> Analysis:
    """What the file is. force = a kind the person chose (bank, card, depot, trades, crypto): the best reading under that kind is used, or unknown when
    the columns do not fit. Never raises."""
    a = Analysis()
    t = read_table(path)
    if t is None or len(t.columns) < 2 or not t.rows:
        a.reasons.append("no table found")
        return a
    cols = _profile(t)
    a.delimiter, a.encoding = t.delimiter, t.encoding
    a.fingerprint = fingerprint_of(t.columns, t.delimiter)
    a.decimals = {c.idx: c.decimal for c in cols}
    a.slashes = {c.idx: c.slash for c in cols}
    scores: dict[str, tuple[float, Analysis]] = {}
    sd = Analysis(**{**a.__dict__, "cols": {}, "reasons": []})
    scores["depot"] = (_score_depot(cols, t, sd), sd)
    sc = Analysis(**{**a.__dict__, "cols": {}, "reasons": []})
    scores["crypto"] = (_score_crypto(cols, t, sc, str(path)), sc)
    sb = Analysis(**{**a.__dict__, "cols": {}, "reasons": []})
    bs, card = _score_bank(cols, t, sb, str(path))
    if scores["depot"][0] >= 0.5 or scores["crypto"][0] >= 0.5:
        bs -= 0.5           # an ISIN / asset-code file is not a bank statement even though it has a date and an amount
    scores["card" if card else "bank"] = (bs, sb)
    if "type" in sd.cols and scores["depot"][0] >= 0.5 and "date" not in sd.cols:
        dc = _find(cols, W_DATE, set(), "date")
        tc = next((c for c in _by_words(cols, W_TYPE, set()) if _sides(c.cells) >= 0.6), None)
        if dc and tc:
            sd.cols.update({"date": dc.idx, "type": tc.idx})
            scores["trades"] = (scores["depot"][0], sd)
            scores["depot"] = (0.0, sd)
    elif scores["depot"][0] >= 0.5:
        tc = next((c for c in _by_words(cols, W_TYPE, set()) if _sides(c.cells) >= 0.6), None)
        dc = _find(cols, W_DATE, set(), "date")
        if tc and dc:
            sd.cols.update({"date": dc.idx, "type": tc.idx})
            scores["trades"] = (scores["depot"][0], sd)
            scores["depot"] = (0.0, sd)
    if force:
        key = force if force in scores else ("bank" if force == "card" and "bank" in scores else force)
        if force == "card" and "card" not in scores and "bank" in scores:
            scores["card"] = scores["bank"]
        if key not in scores or scores[key][0] <= 0.0:
            a.reasons.append(f"the columns do not fit {force}")
            return a
        best_kind = force if force in scores else key
        conf = max(scores[best_kind][0], 0.9)
    else:
        ranked = sorted(scores.items(), key=lambda kv: -kv[1][0])
        best_kind, (conf, _) = ranked[0]
        a.guess = best_kind if conf > 0 else ""
        if conf < MIN_CONFIDENCE or (len(ranked) > 1 and ranked[1][1][0] >= conf - 0.08 and ranked[1][1][0] >= MIN_CONFIDENCE):
            a.reasons.append("not sure what this file is")
            return a
    src = scores[best_kind][1]
    a.kind, a.confidence, a.cols, a.reasons = best_kind, round(conf, 2), src.cols, src.reasons
    a.mapping = {role: t.columns[i] for role, i in a.cols.items()}
    iban_col = cols[a.cols["iban"]] if "iban" in a.cols else None
    a.ident = _ident_from(t, str(path), cols, iban_col)
    if a.kind == "card":
        card_col = next((c for c in cols if c.hn in W_CARD or any(f" {w} " in f" {c.hn} " for w in ("card number", "kartennummer", "karte"))), None)
        if card_col and card_col.cells:
            tail = re.sub(r"\D", "", max(set(card_col.cells), key=card_col.cells.count))[-4:]
            if tail and not a.ident:
                a.ident = "CARD-" + tail
    if a.kind in ("bank", "card"):
        amt = a.cols.get("amount")
        if a.kind == "card" and amt is not None and "direction" not in a.cols:
            vals = [csv_generic.parse_amount(r[amt], cols[amt].decimal) for r in t.rows[:SAMPLE] if _is_num(r[amt])]
            nz = [v for v in vals if v]
            a.flip_sign = bool(nz) and sum(v > 0 for v in nz) >= 0.9 * len(nz)
    if a.kind in ("depot", "trades"):
        dcol = cols[a.cols["date"]] if "date" in a.cols else None
        a.asof, how = _asof_for(t, str(path), dcol if a.kind == "trades" else (dcol if dcol and dcol.date_frac >= 0.8 else None))
        if how:
            a.reasons.append("snapshot date from " + how)
    cur = cols[a.cols["currency"]] if "currency" in a.cols else None
    if cur and cur.cells:
        top = max(set(cur.cells), key=cur.cells.count).upper()
        a.currency = top if top in FIAT else "EUR"
    return a


# ------------------------------------------------------------------ extraction
def _cell(r: list[str], a: Analysis, role: str) -> str:
    i = a.cols.get(role)
    return r[i].strip() if i is not None and i < len(r) else ""


def _date_of(r: list[str], a: Analysis, role: str = "date") -> str | None:
    i = a.cols.get(role)
    return _parse_date_cell(r[i], a.slashes.get(i, "") or csv_generic.DMY) if i is not None else None


def extract_bank(path: str | Path, a: Analysis) -> list[dict[str, Any]]:
    """Booking rows [{date, amount, text, counterparty, balance, iban}] of a bank or card file. Rows that do not parse (totals, notes) are skipped."""
    t = read_table(path)
    if t is None or "date" not in a.cols:
        return []
    out = []
    for r in t.rows:
        d = _date_of(r, a)
        amt = _row_amount(r, a, a.decimals)
        if d is None or amt is None:
            continue
        bi = a.cols.get("balance")
        out.append({"date": d, "amount": amt, "text": _cell(r, a, "text"), "counterparty": _cell(r, a, "counterparty"),
                    "balance": _num(r[bi], a.decimals.get(bi, ",")) if bi is not None else None,
                    "iban": _cell(r, a, "iban").replace(" ", "").upper() if _IBAN.match(_cell(r, a, "iban").replace(" ", "").upper()) else a.ident})
    return out


def _depot_row(r: list[str], a: Analysis) -> dict[str, Any] | None:
    ident = _cell(r, a, "id").upper() if a.cols.get("id") is not None else ""
    if not ident or _num(ident, ",") is not None and len(ident) < 5:
        return None
    qty = _num(_cell(r, a, "qty"), a.decimals.get(a.cols["qty"], ","))
    if qty is None:
        return None
    price = _num(_cell(r, a, "price"), a.decimals.get(a.cols.get("price", -1), ",")) if "price" in a.cols else None
    value = _num(_cell(r, a, "value"), a.decimals.get(a.cols.get("value", -1), ",")) if "value" in a.cols else None
    if value is None and price is not None:
        value = round(qty * price, 2)
    if price is None and value is not None and qty:
        price = round(value / qty, 4)
    cost = _num(_cell(r, a, "cost"), a.decimals.get(a.cols.get("cost", -1), ",")) if "cost" in a.cols else None
    gain = _num(_cell(r, a, "gain"), a.decimals.get(a.cols.get("gain", -1), ",")) if "gain" in a.cols else None
    if gain is None and cost is not None and value is not None:
        gain = round(value - cost, 2)
    pct = round(gain / (value - gain) * 100, 2) if gain is not None and value is not None and value - gain else None
    return {"wkn": ident, "name": _cell(r, a, "name") or ident, "qty": qty, "price": price, "value": value, "gain": gain, "gain_pct": pct}


def extract_depot(path: str | Path, a: Analysis) -> list[tuple[str, list[dict[str, Any]]]]:
    """[(snapshot date ISO, positions)] of a depot file. One snapshot when the file has one date; one per date when it carries a date per row.
    A security listed twice on a date is merged. Position: {wkn (ISIN or id), name, qty, price, value, gain, gain_pct}."""
    t = read_table(path)
    if t is None or "id" not in a.cols:
        return []
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for r in t.rows:
        row = _depot_row(r, a)
        if row is None:
            continue
        day = _date_of(r, a) or a.asof
        if day is None:
            continue
        g = groups.setdefault(day if "date" in a.cols else (a.asof or day), {})
        if row["wkn"] in g:
            m = g[row["wkn"]]
            m["qty"] += row["qty"]
            m["value"] = (m["value"] or 0) + (row["value"] or 0)
            m["price"] = round(m["value"] / m["qty"], 4) if m["qty"] else m["price"]
        else:
            g[row["wkn"]] = row
    return [(d, list(g.values())) for d, g in sorted(groups.items()) if g]


def normalize_asset(code: str) -> str:
    c = code.strip().upper().split(".")[0]
    if c in ASSET_ALIASES:
        return ASSET_ALIASES[c]
    if len(c) == 4 and c[0] in "XZ" and c[1:] in FIAT | {"ETH", "LTC", "XRP", "BTC"}:
        return c[1:]
    return c


def _side_of(text: str, qty: float) -> str:
    h = _hn(text)
    toks = h.split()
    def has(keys: tuple[str, ...]) -> bool:
        return any(k in toks or (len(k) > 3 and k in h) for k in keys)
    if has(_REWARD):
        return "reward"
    if has(_BUY) and not has(_SELL):
        return "buy"
    if has(_SELL):
        return "sell"
    if has(_OUT):
        return "out"
    if has(_IN):
        return "in"
    if has(_TRADE):
        return "buy" if qty > 0 else "sell"
    return "buy" if qty > 0 else "sell"


def extract_crypto(path: str | Path, a: Analysis) -> list[dict[str, Any]]:
    """Crypto transactions [{date (ISO, with time when the file has one), asset, side (buy|sell|in|out|reward), qty (signed: + comes in), price, total, fee,
    currency}], fiat rows left out. total/price are in `currency` (EUR when the file does not say)."""
    t = read_table(path)
    if t is None or "asset" not in a.cols:
        return []
    out = []
    for r in t.rows:
        d = _date_of(r, a)
        qi = a.cols["qty"]
        qty = _num(r[qi], a.decimals.get(qi, ","))
        asset = normalize_asset(_cell(r, a, "asset"))
        if d is None or qty is None or qty == 0 or not asset or asset in FIAT:
            continue
        ti = a.cols["date"]
        side = _side_of(_cell(r, a, "type"), qty) if "type" in a.cols else ("buy" if qty > 0 else "sell")
        q = abs(qty) if side in ("buy", "in", "reward") else -abs(qty) if side in ("sell", "out") else qty
        price = _num(_cell(r, a, "price"), a.decimals.get(a.cols.get("price", -1), ",")) if "price" in a.cols else None
        total = _num(_cell(r, a, "total"), a.decimals.get(a.cols.get("total", -1), ",")) if "total" in a.cols else None
        fee = _num(_cell(r, a, "fee"), a.decimals.get(a.cols.get("fee", -1), ",")) if "fee" in a.cols else None
        if total is None and price is not None:
            total = round(price * abs(q), 2)
        if price is None and total is not None:
            price = round(abs(total) / abs(q), 6)
        cur = _cell(r, a, "currency").upper()
        out.append({"date": d + _time_of(r[ti]), "asset": asset, "side": side, "qty": q, "price": price, "total": abs(total) if total is not None else None,
                    "fee": abs(fee) if fee is not None else None, "currency": cur if cur in FIAT else a.currency})
    return out


def extract_trades(path: str | Path, a: Analysis) -> list[dict[str, Any]]:
    """Securities trades [{date, wkn, side (buy|sell), qty (positive), price, amount}] of a trades file."""
    t = read_table(path)
    if t is None or "id" not in a.cols or "type" not in a.cols:
        return []
    out = []
    for r in t.rows:
        row = _depot_row(r, a)
        d = _date_of(r, a)
        if row is None or d is None:
            continue
        side = _side_of(_cell(r, a, "type"), 1.0)
        if side not in ("buy", "sell"):
            continue
        out.append({"date": d, "wkn": row["wkn"], "side": side, "qty": abs(row["qty"]), "price": row["price"], "amount": abs(row["value"]) if row["value"] is not None else None})
    return out

"""WealthView database, part 8 (v1.20): the things the user types in instead of importing - a house or apartment, a loan, a fund that is not held through a
bank, any other investment - and the balance of a bank account whose files carry no balance. Each typed asset is a source (section "investment", typed in)
with one account and its fields in manual_assets. Writes commit by themselves. Standard library only."""
from __future__ import annotations
import datetime as dt, json, re, sqlite3
from typing import Any

from . import db_accounts
from .db_schema import transaction

ASSET_KINDS = ("property", "loan", "fund", "other")
MAX_NAME = 80
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DOTTED = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")


def _number(v: Any, what: str, *, minimum: float | None = None, maximum: float | None = None, required: bool = True) -> float | None:
    """A number typed in German (1.234,56) or English (1,234.56) style. ValueError with a plain sentence when it is not one."""
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise ValueError(f"{what} is missing")
        return None
    if isinstance(v, bool):
        raise ValueError(f"{what} is not a number")
    if isinstance(v, (int, float)):
        x = float(v)
    else:
        t = re.sub(r"[^\d.,+-]", "", str(v).replace(" ", " "))
        if not re.search(r"\d", t):
            raise ValueError(f"{what} is not a number")
        if "," in t and "." in t:
            dec = "," if t.rfind(",") > t.rfind(".") else "."
        elif "," in t or "." in t:
            mark = "," if "," in t else "."
            tail = t.rsplit(mark, 1)[1]
            dec = "" if (t.count(mark) > 1 or (len(tail) == 3 and t.rsplit(mark, 1)[0].lstrip("+-") not in ("", "0"))) else mark
        else:
            dec = ""
        t = t.replace(".", "").replace(",", ".") if dec == "," else t.replace(",", "") if dec == "." else t.replace(".", "").replace(",", "")
        try:
            x = float(t)
        except ValueError:
            raise ValueError(f"{what} is not a number") from None
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError(f"{what} is not a number")
    if minimum is not None and x < minimum:
        raise ValueError(f"{what} must be at least {minimum:g}")
    if maximum is not None and x > maximum:
        raise ValueError(f"{what} must be at most {maximum:g}")
    return round(x, 6)


def _date(v: Any, what: str, required: bool = True) -> str | None:
    """ISO date from 2026-11-13 or 13.11.2026."""
    s = str(v).strip() if v is not None else ""
    if not s:
        if required:
            raise ValueError(f"{what} is missing")
        return None
    m = _DOTTED.match(s)
    if m:
        s = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    if not _ISO.match(s):
        raise ValueError(f"{what} must look like 2026-11-13 or 13.11.2026")
    try:
        dt.date.fromisoformat(s)
    except ValueError:
        raise ValueError(f"{what} is not a real date") from None
    return s


def _name(f: dict[str, Any]) -> str:
    n = str(f.get("name") or "").strip()
    if not n:
        raise ValueError("a name is needed")
    if len(n) > MAX_NAME:
        raise ValueError(f"the name is longer than {MAX_NAME} characters")
    return n


def validate(kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    """The cleaned fields of a typed asset, or ValueError with a plain sentence for the person.
    property: name, country (2 letters), purchase_price, purchase_date, optional current_estimate, size_m2.
    loan: name, amount, start_date, rate_pct, monthly or end_date, optional property (name of a property).
    fund: name, payments [{date, amount}] (or invested + since), optional current_value, isin.   other: name, value, optional date."""
    if kind not in ASSET_KINDS:
        raise ValueError(f"unknown kind: {kind}")
    if not isinstance(raw, dict):
        raise ValueError("the details must be an object")
    out: dict[str, Any] = {"name": _name(raw)}
    if kind == "property":
        country = str(raw.get("country") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError("the country must be a two-letter code such as DE")
        out["country"] = country
        out["purchase_price"] = _number(raw.get("purchase_price"), "the purchase price", minimum=1)
        out["purchase_date"] = _date(raw.get("purchase_date"), "the purchase date")
        for k, what in (("current_estimate", "the current estimate"), ("size_m2", "the size")):
            v = _number(raw.get(k), what, minimum=1, required=False)
            if v is not None:
                out[k] = v
    elif kind == "loan":
        out["amount"] = _number(raw.get("amount"), "the amount borrowed", minimum=1)
        out["start_date"] = _date(raw.get("start_date"), "the start date")
        out["rate_pct"] = _number(raw.get("rate_pct"), "the interest rate", minimum=0, maximum=30)
        monthly = _number(raw.get("monthly"), "the monthly payment", minimum=0.01, required=False)
        end = _date(raw.get("end_date"), "the end date", required=False)
        if monthly is None and end is None:
            raise ValueError("give the monthly payment or the end date of the loan")
        if monthly is not None:
            out["monthly"] = monthly
        if end is not None:
            out["end_date"] = end
        if str(raw.get("property") or "").strip():
            out["property"] = str(raw["property"]).strip()[:MAX_NAME]
    elif kind == "fund":
        pays = raw.get("payments")
        if isinstance(pays, list) and pays:
            out["payments"] = [{"date": _date(p.get("date"), "a payment date"), "amount": _number(p.get("amount"), "a payment amount")}
                               for p in pays if isinstance(p, dict)]
        else:
            out["payments"] = [{"date": _date(raw.get("since"), "the date of the payment"), "amount": _number(raw.get("invested"), "the amount paid in")}]
        cv = _number(raw.get("current_value"), "the current value", minimum=0, required=False)
        if cv is not None:
            out["current_value"] = cv
        if str(raw.get("isin") or "").strip():
            out["isin"] = str(raw["isin"]).strip().upper()[:12]
    else:
        out["value"] = _number(raw.get("value"), "the value", minimum=0)
        d = _date(raw.get("date"), "the date", required=False)
        if d:
            out["date"] = d
    return out


def add_asset(conn: sqlite3.Connection, kind: str, raw: dict[str, Any]) -> int:
    """Validate and store a typed asset; returns its account id. ValueError for bad input (nothing is stored)."""
    fields = validate(kind, raw)
    with transaction(conn):
        sid = db_accounts.add_source(conn, fields["name"], "investment", "manual", reader="none", options={"asset": kind})
        aid = db_accounts.account_for(conn, sid, "manual", fields["name"], kind)
        conn.execute("INSERT OR REPLACE INTO manual_assets(account_id, fields) VALUES(?,?)", (aid, json.dumps(fields)))
    return aid


def update_asset(conn: sqlite3.Connection, account_id: int, raw: dict[str, Any]) -> None:
    """Replace the fields of a typed asset (the name too). KeyError for an unknown account."""
    row = conn.execute("SELECT a.kind, a.source_id FROM accounts a JOIN manual_assets m ON m.account_id=a.id WHERE a.id=?", (account_id,)).fetchone()
    if row is None:
        raise KeyError(account_id)
    fields = validate(row[0], raw)
    with transaction(conn):
        conn.execute("UPDATE manual_assets SET fields=? WHERE account_id=?", (json.dumps(fields), account_id))
        conn.execute("UPDATE accounts SET name=? WHERE id=?", (fields["name"], account_id))
        conn.execute("UPDATE sources SET name=? WHERE id=?", (fields["name"], row[1]))


def delete_asset(conn: sqlite3.Connection, account_id: int) -> None:
    """Remove a typed asset with its account, its source and its stored values."""
    row = conn.execute("SELECT a.source_id FROM accounts a JOIN manual_assets m ON m.account_id=a.id WHERE a.id=?", (account_id,)).fetchone()
    if row is None:
        return
    with transaction(conn):
        conn.execute("DELETE FROM valuations WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM manual_assets WHERE account_id=?", (account_id,))
        conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        if not conn.execute("SELECT 1 FROM accounts WHERE source_id=?", (row[0],)).fetchone():
            conn.execute("DELETE FROM sources WHERE id=?", (row[0],))


def list_assets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """[{account_id, source_id, kind, name, fields}] of the active typed assets, in the order they were added."""
    out = []
    for r in conn.execute("SELECT a.id, a.source_id, a.kind, a.name, m.fields FROM manual_assets m JOIN accounts a ON a.id=m.account_id "
                          "JOIN sources s ON s.id=a.source_id WHERE a.active=1 AND s.active=1 ORDER BY a.id"):
        try:
            fields = json.loads(r[4])
        except ValueError:
            continue
        out.append({"account_id": r[0], "source_id": r[1], "kind": r[2], "name": r[3], "fields": fields})
    return out


def set_typed_balance(conn: sqlite3.Connection, account_id: int, value: float, day: str) -> None:
    """The balance of a bank account whose files carry no balance column, as the person typed it (the newest one counts)."""
    v = _number(value, "the balance")
    d = _date(day, "the date")
    with transaction(conn):
        conn.execute("INSERT OR REPLACE INTO valuations(account_id, date, value, basis) VALUES(?,?,?,'typed')", (account_id, d, v))


def typed_balances(conn: sqlite3.Connection) -> dict[int, tuple[float, str]]:
    """{account id: (balance, date)} - the newest typed balance of each account."""
    out: dict[int, tuple[float, str]] = {}
    for aid, d, v in conn.execute("SELECT account_id, date, value FROM valuations WHERE basis='typed' ORDER BY date, rowid"):
        out[int(aid)] = (float(v), d)
    return out

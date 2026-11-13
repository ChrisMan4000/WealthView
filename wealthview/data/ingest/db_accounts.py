"""WealthView database, part 4 (v1.19): sources and accounts.
A source is one thing the user set up (a bank, an investment, a crypto place) with where its data comes from: a folder, an API, or typed in.
An account is what is found inside a source (current account, card, depot, wallet). Bookings, PayPal rows and depot positions point to an account.
Writes do not commit: callers wrap them in db_schema.transaction(). Standard library only."""
from __future__ import annotations
import datetime as dt, json, sqlite3
from typing import Any

from ...common.types.accounts import AccountRow, SourceRow
from .db_schema import KINDS, SECTIONS, SOURCE_TYPES

NO_IDENT = "-"          # stored when an account has no IBAN / id, so UNIQUE(source_id, ident) also covers "unknown account"


_SOURCE_COLS = "SELECT id,name,section,source_type,folder,connector,reader,options,active,legacy_key FROM sources"
_SOURCES_ALL = _SOURCE_COLS + " ORDER BY id"
_SOURCES_ACTIVE = _SOURCE_COLS + " WHERE active=1 ORDER BY id"
_KIND_QUERIES = (            # fixed queries: table names are never built from outside values
    "SELECT DISTINCT a.kind FROM accounts a JOIN bookings t ON t.account_id = a.id",
    "SELECT DISTINCT a.kind FROM accounts a JOIN paypal_tx t ON t.account_id = a.id",
    "SELECT DISTINCT a.kind FROM accounts a JOIN depot_positions t ON t.account_id = a.id",
)


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def add_source(conn: sqlite3.Connection, name: str, section: str, source_type: str, *, folder: str | None = None, connector: str | None = None,
               reader: str = "auto", options: dict[str, Any] | None = None, legacy_key: str | None = None) -> int:
    """Create a source and return its id. With a legacy_key that already exists the existing id is returned and nothing changes."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a source needs a name")
    if section not in SECTIONS:
        raise ValueError(f"unknown section: {section}")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"unknown source type: {source_type}")
    if source_type == "folder" and not folder:
        raise ValueError("a folder source needs a folder")
    if legacy_key:
        row = conn.execute("SELECT id FROM sources WHERE legacy_key=?", (legacy_key,)).fetchone()
        if row:
            return int(row[0])
    cur = conn.execute("INSERT INTO sources(name,section,source_type,folder,connector,reader,options,created,legacy_key) VALUES(?,?,?,?,?,?,?,?,?)",
                       (name, section, source_type, folder, connector, reader, json.dumps(options or {}), _now(), legacy_key))
    return int(cur.lastrowid or 0)


def _options(text: str | None) -> dict[str, Any]:
    try:
        val = json.loads(text) if text else {}
    except ValueError:
        return {}
    return val if isinstance(val, dict) else {}


def list_sources(conn: sqlite3.Connection, active_only: bool = True) -> list[SourceRow]:
    """The sources in the order they were added (inactive ones only with active_only=False)."""
    sql = _SOURCES_ACTIVE if active_only else _SOURCES_ALL
    return [SourceRow(id=r[0], name=r[1], section=r[2], source_type=r[3], folder=r[4], connector=r[5], reader=r[6], options=_options(r[7]),
                      active=bool(r[8]), legacy_key=r[9]) for r in conn.execute(sql)]


def set_source_active(conn: sqlite3.Connection, source_id: int, active: bool) -> None:
    conn.execute("UPDATE sources SET active=? WHERE id=?", (1 if active else 0, source_id))


def account_for(conn: sqlite3.Connection, source_id: int, ident: str | None, name: str, kind: str, currency: str = "EUR") -> int:
    """The id of the account (source, ident); created on first use. An existing account keeps its name and kind."""
    if kind not in KINDS:
        raise ValueError(f"unknown account kind: {kind}")
    ident = (ident or "").strip() or NO_IDENT
    row = conn.execute("SELECT id FROM accounts WHERE source_id=? AND ident=?", (source_id, ident)).fetchone()
    if row:
        return int(row[0])
    cur = conn.execute("INSERT INTO accounts(source_id,name,kind,ident,currency,created) VALUES(?,?,?,?,?,?)",
                       (source_id, (name or "").strip() or "Account", kind, ident, currency or "EUR", _now()))
    return int(cur.lastrowid or 0)


def list_accounts(conn: sqlite3.Connection, source_id: int | None = None) -> list[AccountRow]:
    sql = "SELECT id,source_id,name,kind,ident,currency,active FROM accounts"
    args: tuple[int, ...] = ()
    if source_id is not None:
        sql, args = sql + " WHERE source_id=?", (source_id,)
    return [AccountRow(id=r[0], source_id=r[1], name=r[2], kind=r[3], ident=r[4], currency=r[5], active=bool(r[6])) for r in conn.execute(sql + " ORDER BY id", args)]


def kinds_with_data(conn: sqlite3.Connection) -> set[str]:
    """The account kinds that have at least one imported row (booking, PayPal row or depot position)."""
    out: set[str] = set()
    for sql in _KIND_QUERIES:
        out |= {r[0] for r in conn.execute(sql)}
    return out

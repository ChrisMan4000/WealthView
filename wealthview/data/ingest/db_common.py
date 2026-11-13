"""WealthView database, part 1b (v1.20): small helpers shared by the importers (db_import, db_auto): the booking key, the file bookkeeping line and the
link from bookings to their account. Standard library only."""
from __future__ import annotations
import hashlib, sqlite3

from ...common.types.accounts import SourceRow
from . import db_accounts

def finish_file(conn: sqlite3.Connection, fid: int | None, rows: int, new_rows: int, d_from: str | None = None, d_to: str | None = None, note: str | None = None) -> None:
    conn.execute("UPDATE files SET rows=?, new_rows=?, d_from=?, d_to=?, note=? WHERE id=?", (rows, new_rows, d_from, d_to, note, fid))


def booking_key(iban: str, date: str, amount: float, balance: float | None, purpose: str | None, counterparty: str | None) -> str:
    s = "|".join(str(x) for x in (iban, date, amount, balance, (purpose or "")[:80], (counterparty or "")[:30]))
    return hashlib.sha1(s.encode("utf-8"), usedforsecurity=False).hexdigest()


def link_bookings(conn: sqlite3.Connection, source: SourceRow | None, accounts: dict[str, tuple[str, str]]) -> None:
    """Point the bookings of {iban: (account label, kind)} that have no account yet to their account in `source` (created on first use).
    Rows that already belong to an account keep it. Nothing happens without a source (old shape)."""
    if source is None:
        return
    for iban, (label, kind) in accounts.items():
        known = conn.execute("SELECT id FROM accounts WHERE ident=? ORDER BY id LIMIT 1", (iban,)).fetchone() if iban else None
        # an IBAN is one account, whichever source's file delivers its rows (overlapping or nested folders must not split it)
        acc = int(known[0]) if known else db_accounts.account_for(conn, source["id"], iban, label, "card" if kind == "card" else "bank")
        conn.execute("UPDATE bookings SET account_id=? WHERE COALESCE(iban,'')=? AND account_id IS NULL", (acc, iban or ""))

"""WealthView database, part 7 (v1.20): importing a file of a folder source whose reader is "auto". Known bank exports (GLS, PayPal) still go to their own
importers; every other file goes through autoread.analyze(): bank and card files become bookings, depot files positions, trades files trades (plus a
depot derived from them), crypto files crypto transactions. A file the reader cannot place waits for one plain answer (db_questions) and is read again
once it is answered. Standard library only."""
from __future__ import annotations
import hashlib, sqlite3
from pathlib import Path
from typing import Any

from ...common.types.accounts import SourceRow
from . import autoread, db_accounts, db_questions, gls_parse, plugins
from .db_common import booking_key, finish_file as _finish_file, link_bookings as _link_bookings

AUTO_SUFFIXES = (".csv", ".txt")
LEGACY_KIND = {"gls": "gls", "gls_depot": "depot", "paypal": "paypal"}


def import_auto_file(conn: sqlite3.Connection, path: str | Path, fid: int | None, source: SourceRow, legacy: dict[str, Any]) -> tuple[int, int, str]:
    """-> (rows, new rows, kind). kind: gls / depot / paypal (known exports), bank / card / depot / trades / crypto (read by autoread), or 'waiting' /
    'skipped' when nothing was imported (a question was asked / the person chose to skip this layout). Raises UnsupportedFile for a file that cannot be read."""
    p = str(path)
    hit = plugins.detect_best(p)
    if hit is not None and hit[0] in legacy:
        n, new = legacy[hit[0]](conn, path, fid, source)
        return n, new, LEGACY_KIND[hit[0]]
    a = autoread.analyze(p)
    if not a.fingerprint:
        raise gls_parse.UnsupportedFile("not a table of values")
    learned = db_questions.format_for(conn, a.fingerprint)
    if learned == "skip":
        _finish_file(conn, fid, 0, 0, note="skipped: you chose to skip files like this")
        return 0, 0, "skipped"
    if learned:
        a = autoread.analyze(p, force=learned)
        if a.kind == "unknown":
            raise gls_parse.UnsupportedFile(f"cannot be read as {learned}")
    elif a.kind == "unknown":
        db_questions.ask(conn, source["id"], Path(p).name, p, a.fingerprint, a.guess)
        _finish_file(conn, fid, 0, 0, note=db_questions.WAITING)
        return 0, 0, "waiting"
    importer = {"bank": _bank, "card": _bank, "depot": _depot, "trades": _trades, "crypto": _crypto}[a.kind]
    n, new = importer(conn, p, fid, source, a)
    return n, new, a.kind


def _bank(conn: sqlite3.Connection, path: str, fid: int | None, source: SourceRow, a: autoread.Analysis) -> tuple[int, int]:
    import datetime as dt
    rows = autoread.extract_bank(path, a)
    fallback = "AUTO-" + a.fingerprint[:8].upper()
    kind = "card" if a.kind == "card" else "giro"
    fkey = dt.date.fromtimestamp(Path(path).stat().st_mtime).toordinal()
    known = {r[0] for r in conn.execute("SELECT bkey FROM bookings")}
    idents = sorted({r["iban"] or fallback for r in rows})
    label = {i: (source["name"] if len(idents) == 1 else f"{source['name']} {i[-4:]}") for i in idents}
    seen: dict[str, int] = {}
    new = 0
    for i, r in enumerate(rows):
        ident = r["iban"] or fallback
        base = booking_key(ident, r["date"], r["amount"], r["balance"], r["text"], r["counterparty"])
        n = seen[base] = seen.get(base, -1) + 1
        k = base if n == 0 else booking_key(f"{ident}#{n}", r["date"], r["amount"], r["balance"], r["text"], r["counterparty"])
        new += k not in known
        known.add(k)
        conn.execute(
            "INSERT INTO bookings(bkey,account,kind,iban,date,counterparty,cp_iban,type,purpose,amount,balance,category,file_id,fkey,ord) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(bkey) DO UPDATE SET fkey=excluded.fkey, ord=excluded.ord, file_id=excluded.file_id "
            "WHERE excluded.fkey > bookings.fkey",
            (k, label[ident], kind, ident, r["date"], r["counterparty"], "", "", r["text"], r["amount"], r["balance"], "", fid, fkey, i))
    _link_bookings(conn, source, {i: (label[i], kind) for i in idents} if rows else {})
    dates = [r["date"] for r in rows]
    _finish_file(conn, fid, len(rows), new, min(dates) if dates else None, max(dates) if dates else None)
    return len(rows), new


def _depot_account(conn: sqlite3.Connection, source: SourceRow, a: autoread.Analysis) -> int:
    return db_accounts.account_for(conn, source["id"], a.ident or "depot", source["name"], "depot", a.currency)


def _depot(conn: sqlite3.Connection, path: str, fid: int | None, source: SourceRow, a: autoread.Analysis) -> tuple[int, int]:
    snaps = autoread.extract_depot(path, a)
    if not snaps:
        raise gls_parse.UnsupportedFile("no depot positions found")
    acc = _depot_account(conn, source, a)
    n = 0
    for asof, pos in snaps:
        for x in pos:
            conn.execute("INSERT OR REPLACE INTO depot_positions(account_id,asof,wkn,name,qty,price,value,gain,gain_pct,file_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (acc, asof, x["wkn"], x["name"], x["qty"], x["price"], x["value"], x["gain"], x["gain_pct"], fid))
            n += 1
    _finish_file(conn, fid, n, n, snaps[0][0], snaps[-1][0])
    return n, n


def _trades(conn: sqlite3.Connection, path: str, fid: int | None, source: SourceRow, a: autoread.Analysis) -> tuple[int, int]:
    rows = autoread.extract_trades(path, a)
    if not rows:
        raise gls_parse.UnsupportedFile("no securities trades found")
    new = 0
    for r in rows:
        tkey = hashlib.sha1("|".join(str(x) for x in (r["wkn"], r["date"], r["side"], r["qty"], r["price"])).encode("utf-8"), usedforsecurity=False).hexdigest()
        new += conn.execute("INSERT OR IGNORE INTO trades(tkey,wkn,date,side,qty,price,amount) VALUES(?,?,?,?,?,?,?)",
                            (tkey, r["wkn"], r["date"], r["side"], r["qty"], r["price"], r["amount"])).rowcount
    names = {r["wkn"]: r.get("name") or r["wkn"] for r in rows}
    held: dict[str, list[float]] = {}
    for wkn, side, qty, price in conn.execute("SELECT wkn,side,qty,price FROM trades ORDER BY date, rowid"):
        h = held.setdefault(wkn, [0.0, 0.0])
        h[0] += qty if side == "buy" else -qty
        h[1] = price or h[1]
    asof = max(r["date"] for r in rows)
    acc = _depot_account(conn, source, a)
    conn.execute("DELETE FROM depot_positions WHERE account_id=? AND asof=?", (acc, asof))
    for wkn, (qty, price) in held.items():
        if qty > 1e-9:
            conn.execute("INSERT OR REPLACE INTO depot_positions(account_id,asof,wkn,name,qty,price,value,gain,gain_pct,file_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (acc, asof, wkn, names.get(wkn, wkn), qty, price, round(qty * price, 2), None, None, fid))
    _finish_file(conn, fid, len(rows), new, min(r["date"] for r in rows), asof)
    return len(rows), new


def _crypto(conn: sqlite3.Connection, path: str, fid: int | None, source: SourceRow, a: autoread.Analysis) -> tuple[int, int]:
    rows = autoread.extract_crypto(path, a)
    if not rows:
        raise gls_parse.UnsupportedFile("no crypto transactions found")
    acc = db_accounts.account_for(conn, source["id"], a.ident or "crypto", source["name"], "crypto", a.currency)
    seen: dict[str, int] = {}
    new = 0
    for r in rows:
        base = "|".join(str(x) for x in (acc, r["date"], r["asset"], r["side"], r["qty"], r["total"]))
        n = seen[base] = seen.get(base, -1) + 1
        key = hashlib.sha1((base + (f"#{n}" if n else "")).encode("utf-8"), usedforsecurity=False).hexdigest()
        new += conn.execute("INSERT OR IGNORE INTO crypto_tx(ckey,account_id,date,asset,side,qty,price,total,fee,currency,file_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (key, acc, r["date"], r["asset"], r["side"], r["qty"], r["price"], r["total"], r["fee"], r["currency"], fid)).rowcount
    dates = [r["date"][:10] for r in rows]
    _finish_file(conn, fid, len(rows), new, min(dates), max(dates))
    return len(rows), new


def summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """What the automatic reader has stored so far (for the status line and the tests)."""
    return {"crypto_tx": conn.execute("SELECT COUNT(*) FROM crypto_tx").fetchone()[0], "questions": len(db_questions.open_questions(conn))}

"""WealthView database, part 3: reading and storing results - load_gls_rows() (bookings in the shape the pipeline uses), coverage() (per account first/last booking and
months without any booking), the daily snapshots, trades, spending and monthly tables, the dismissed-unusual-bookings list and counts()."""
from __future__ import annotations
from typing import Any
import hashlib, json, sqlite3
from collections.abc import Sequence
import datetime as dt

from ...common.timeutil import month_key, mrange
from ...common.types.bookings import BookingRow, Coverage, FlowModel, SpendingRow
from ...common.types.depot import Trade
from .db_schema import meta_get, meta_set, transaction


UNUSUAL_SEEN_KEY = "unusual_seen"


UNUSUAL_SEEN_CAP = 500


UNUSUAL_KEY_MAX = 200


def unusual_seen_get(conn: sqlite3.Connection) -> list[str]:
    """Dismissed 'Unusual bookings' keys, oldest first."""
    try:
        v = json.loads(meta_get(conn, UNUSUAL_SEEN_KEY, "[]") or "[]")
    except ValueError:
        return []
    return [k for k in v if isinstance(k, str)] if isinstance(v, list) else []


def unusual_seen_add(conn: sqlite3.Connection, keys: object) -> list[str]:
    """Add dismissed keys (strings up to 200 chars; anything else is ignored); keeps the newest 500. Returns the stored list."""
    new = [k for k in (keys if isinstance(keys, list) else []) if isinstance(k, str) and 0 < len(k) <= UNUSUAL_KEY_MAX]
    with transaction(conn):
        cur = unusual_seen_get(conn)
        already = set(new)                       # built once, not once per element
        merged = [k for k in cur if k not in already] + list(dict.fromkeys(new))
        merged = merged[-UNUSUAL_SEEN_CAP:]
        meta_set(conn, UNUSUAL_SEEN_KEY, json.dumps(merged, ensure_ascii=False))
    return merged


# Fixed row-count queries (table names are never taken from outside this module).
_COUNT_QUERIES = {
    "bookings": "SELECT COUNT(*) FROM bookings",
    "paypal_tx": "SELECT COUNT(*) FROM paypal_tx",
    "depot_positions": "SELECT COUNT(*) FROM depot_positions",
    "trades": "SELECT COUNT(*) FROM trades",
    "snapshots": "SELECT COUNT(*) FROM snapshots",
    "files": "SELECT COUNT(*) FROM files",
}


def load_gls_rows(conn: sqlite3.Connection) -> list[BookingRow]:
    """All bookings as the dicts loaders.load_gls() returns (newest first; ties keep the newest file's order)."""
    out: list[BookingRow] = []
    for r in conn.execute("SELECT * FROM bookings ORDER BY date DESC, fkey DESC, ord ASC, id ASC"):
        out.append(BookingRow(iban=r["iban"] or "", account=r["account"] or "", date=dt.date.fromisoformat(r["date"]), counterparty=r["counterparty"] or "",
                        cp_iban=r["cp_iban"] or "", typ=r["type"] or "", purpose=r["purpose"] or "", amount=r["amount"], balance=r["balance"],
                        cat=r["category"] or "", kind=r["kind"] or "giro"))
    return out


def coverage(conn: sqlite3.Connection, today: dt.date | None = None, min_rows: int = 24, min_per_month: float = 3.0) -> list[Coverage]:
    """Per account: first/last booking, count, and months without any booking (only for busy accounts) = holes in the downloads."""
    today = today or dt.date.today()
    out: list[Coverage] = []
    for r in conn.execute("SELECT iban, MAX(account) acct, MAX(kind) kind, MIN(date) d0, MAX(date) d1, COUNT(*) n FROM bookings GROUP BY iban ORDER BY n DESC"):
        d0, d1 = dt.date.fromisoformat(r["d0"]), dt.date.fromisoformat(r["d1"])
        have = {x[0] for x in conn.execute("SELECT DISTINCT substr(date,1,7) FROM bookings WHERE iban=?", (r["iban"],))}
        allm = mrange(month_key(d0), month_key(d1))
        gaps = [m for m in allm if m not in have] if (r["n"] >= min_rows and r["n"] / max(1, len(allm)) >= min_per_month) else []
        out.append(Coverage(iban=r["iban"], account=r["acct"], kind=r["kind"], first=r["d0"], last=r["d1"], n=r["n"],
                            age_days=(today - d1).days, gap_months=gaps))
    return out


def store_trades(conn: sqlite3.Connection, trades: dict[str, list[Trade]] | None) -> None:
    """trades = {wkn: [dict(d, side, qty, price, amount)]} as lots.parse_trades() returns."""
    with transaction(conn):
        for wkn, lst in (trades or {}).items():
            for t in lst:
                k = hashlib.sha1(f"{wkn}|{t['d']}|{t['side']}|{t['qty']}|{t['price']}".encode(), usedforsecurity=False).hexdigest()
                conn.execute("INSERT OR REPLACE INTO trades(tkey,wkn,date,side,qty,price,amount) VALUES(?,?,?,?,?,?,?)",
                             (k, wkn, t["d"], t["side"], t["qty"], t["price"], t.get("amount")))


def record_snapshot_rows(conn: sqlite3.Connection, day: str, items: Sequence[tuple[str, str, float | None, float | None]]) -> None:
    """items = [(scope, key, value, extra)]; one row per (day, scope, key) - the last write of the day wins."""
    now = dt.datetime.now().isoformat(timespec="seconds")
    with transaction(conn):
        for scope, key, value, extra in items:
            if value is None:
                continue
            conn.execute("INSERT OR REPLACE INTO snapshots(day,scope,key,value,extra,updated_at) VALUES(?,?,?,?,?,?)", (day, scope, key, value, extra, now))


def seed_snapshots_from_history(conn: sqlite3.Connection, hist: list[dict[str, Any]] | None) -> int:
    """Seed snapshots from the early history.json entries (t, assets, per class) for days not yet recorded; harmless to repeat."""
    have = {r[0] for r in conn.execute("SELECT DISTINCT day FROM snapshots")}
    last = {}
    for h in hist or []:
        last[str(h.get("t", ""))[:10]] = h            # last entry of each day
    n = 0
    for day, h in sorted(last.items()):
        if not day or day in have:
            continue
        items = [("total", "gross", h.get("assets"), None)] + [("class", k, v, None) for k, v in h.items() if k not in ("t", "assets") and isinstance(v, (int, float))]
        record_snapshot_rows(conn, day, items)
        n += 1
    return n


def store_spending(conn: sqlite3.Connection, spend: list[SpendingRow] | None) -> None:
    """Real spending only (no income, internal moves, card settlements, investments) as bookings.spending_rows() classifies it.
    Rebuilt on every full refresh, so a better classifier shows up in old months too. amount < 0 = money out."""
    with transaction(conn):
        conn.execute("DELETE FROM spending")
        conn.executemany("INSERT INTO spending(date,merchant,category,amount) VALUES(?,?,?,?)",
                         [(r["date"], r["merchant"], r["category"], r["amount"]) for r in spend or []])


def store_monthly(conn: sqlite3.Connection, flows: FlowModel | None) -> None:
    """Monthly income / expense / savings and spending per category from bookings.build_flow_model() (positive numbers)."""
    if not flows:
        return
    rows: list[tuple[Any, ...]] = []
    for i, m in enumerate(flows["months"]):
        rows += [(m, "income", flows["income"][i]), (m, "expense", flows["expense"][i]), (m, "savings", flows["income"][i] - flows["expense"][i])]
        rows += [(m, "cat:" + c, s[i]) for c, s in flows["cats"].items()]
    with transaction(conn):
        conn.execute("DELETE FROM monthly")
        conn.executemany("INSERT INTO monthly(month,item,amount) VALUES(?,?,?)", rows)


def counts(conn: sqlite3.Connection) -> dict[str, int | str | None]:
    out: dict[str, int | str | None] = {}
    for t, sql in _COUNT_QUERIES.items():
        out[t] = conn.execute(sql).fetchone()[0]
    r = conn.execute("SELECT MIN(date), MAX(date) FROM bookings").fetchone()
    out["bookings_from"], out["bookings_to"] = r[0], r[1]
    r = conn.execute("SELECT MIN(day), COUNT(DISTINCT day) FROM snapshots WHERE scope='total'").fetchone()
    out["snap_from"], out["snap_days"] = r[0], r[1]
    return out

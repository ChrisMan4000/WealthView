"""WealthView database, part 1: the SQLite file `wealthview.db` in data/ - table definitions, connect(), transaction() and the small key-value store (meta).
Part 2 (importing the watched folders) is db_import.py, part 3 (reading and storing results) is db_queries.py. Standard library only."""
from __future__ import annotations
import contextlib, sqlite3
from collections.abc import Iterator
from pathlib import Path



DB_NAME = "wealthview.db"


SCHEMA_VERSION = 1


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, name TEXT NOT NULL, size INTEGER, sha TEXT UNIQUE,
  rows INTEGER DEFAULT 0, new_rows INTEGER DEFAULT 0, d_from TEXT, d_to TEXT, imported_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS file_seen(path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, sha TEXT);
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY, bkey TEXT NOT NULL UNIQUE, account TEXT, kind TEXT, iban TEXT, date TEXT NOT NULL,
  counterparty TEXT, cp_iban TEXT, type TEXT, purpose TEXT, amount REAL NOT NULL, balance REAL, category TEXT,
  file_id INTEGER, fkey INTEGER DEFAULT 0, ord INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date);
CREATE INDEX IF NOT EXISTS idx_bookings_kind ON bookings(kind, date);
CREATE TABLE IF NOT EXISTS paypal_tx(
  id INTEGER PRIMARY KEY, pkey TEXT NOT NULL UNIQUE, date TEXT NOT NULL, time TEXT, name TEXT, type TEXT, status TEXT,
  currency TEXT, gross REAL, fee REAL, net REAL, balance REAL, code TEXT, subject TEXT, file_id INTEGER);
CREATE INDEX IF NOT EXISTS idx_paypal_date ON paypal_tx(date);
CREATE TABLE IF NOT EXISTS depot_positions(
  asof TEXT NOT NULL, wkn TEXT NOT NULL, name TEXT, qty REAL, price REAL, value REAL, gain REAL, gain_pct REAL, file_id INTEGER,
  PRIMARY KEY(asof, wkn));
CREATE TABLE IF NOT EXISTS trades(
  tkey TEXT PRIMARY KEY, wkn TEXT NOT NULL, date TEXT NOT NULL, side TEXT NOT NULL, qty REAL, price REAL, amount REAL);
CREATE TABLE IF NOT EXISTS spending(
  date TEXT NOT NULL, merchant TEXT, category TEXT, amount REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_spending_date ON spending(date);
CREATE TABLE IF NOT EXISTS monthly(
  month TEXT NOT NULL, item TEXT NOT NULL, amount REAL, PRIMARY KEY(month, item));
CREATE TABLE IF NOT EXISTS cat_rules(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, pattern TEXT NOT NULL, category TEXT NOT NULL, created TEXT,
  UNIQUE(kind, pattern));
CREATE TABLE IF NOT EXISTS cat_overrides(
  okey TEXT PRIMARY KEY, category TEXT NOT NULL, label TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS snapshots(
  day TEXT NOT NULL, scope TEXT NOT NULL, key TEXT NOT NULL, value REAL, extra REAL, updated_at TEXT,
  PRIMARY KEY(day, scope, key));
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    init(conn)
    return conn


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """`with transaction(conn):` commits when the block finishes and rolls back (then re-raises) when it fails."""
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def init(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.executescript(SCHEMA)
        conn.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))


def meta_get(conn: sqlite3.Connection, k: str, default: str | None = None) -> str | None:
    r = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def meta_set(conn: sqlite3.Connection, k: str, v: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, v))

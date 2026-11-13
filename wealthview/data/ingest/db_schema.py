"""WealthView database, part 1: the SQLite file `wealthview.db` in data/ - table definitions, connect(), transaction() and the small key-value store (meta).
Part 2 (importing the watched folders) is db_import.py, part 3 (reading and storing results) is db_queries.py. Standard library only."""
from __future__ import annotations
import contextlib, sqlite3
from collections.abc import Iterator
from pathlib import Path



DB_NAME = "wealthview.db"


SCHEMA_VERSION = 2          # 2 (v1.19): sources + accounts; an older database is upgraded once by db_migrate.upgrade()

KINDS = ("bank", "card", "depot", "crypto", "property", "loan", "fund", "other")     # what an account is
SECTIONS = ("bank", "investment", "crypto")                                          # the three setup steps a source belongs to
SOURCE_TYPES = ("folder", "api", "manual")                                           # where a source's data comes from


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
  account_id INTEGER NOT NULL DEFAULT 0, asof TEXT NOT NULL, wkn TEXT NOT NULL, name TEXT, qty REAL, price REAL, value REAL, gain REAL,
  gain_pct REAL, file_id INTEGER, PRIMARY KEY(account_id, asof, wkn));
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
CREATE TABLE IF NOT EXISTS sources(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, section TEXT NOT NULL, source_type TEXT NOT NULL,
  folder TEXT, connector TEXT, reader TEXT NOT NULL DEFAULT 'auto', options TEXT,
  active INTEGER NOT NULL DEFAULT 1, created TEXT, legacy_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), name TEXT NOT NULL, kind TEXT NOT NULL,
  ident TEXT, currency TEXT NOT NULL DEFAULT 'EUR', active INTEGER NOT NULL DEFAULT 1, created TEXT,
  UNIQUE(source_id, ident));
CREATE TABLE IF NOT EXISTS manual_assets(account_id INTEGER PRIMARY KEY REFERENCES accounts(id), fields TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS valuations(
  account_id INTEGER NOT NULL, date TEXT NOT NULL, value REAL NOT NULL, basis TEXT NOT NULL, PRIMARY KEY(account_id, date, basis));
CREATE TABLE IF NOT EXISTS formats(fingerprint TEXT PRIMARY KEY, kind TEXT NOT NULL, mapping TEXT NOT NULL, confirmed INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS questions(
  id INTEGER PRIMARY KEY, source_id INTEGER, file TEXT, topic TEXT NOT NULL, options TEXT NOT NULL, answer TEXT,
  status TEXT NOT NULL DEFAULT 'open', created TEXT);
"""

_HAS_DATA = ("SELECT 1 FROM bookings LIMIT 1", "SELECT 1 FROM paypal_tx LIMIT 1", "SELECT 1 FROM depot_positions LIMIT 1")   # any hit: not "new"
_NEW_COLUMNS = (("bookings", "account_id", "ALTER TABLE bookings ADD COLUMN account_id INTEGER"),
                ("paypal_tx", "account_id", "ALTER TABLE paypal_tx ADD COLUMN account_id INTEGER"),
                ("files", "source_id", "ALTER TABLE files ADD COLUMN source_id INTEGER"))


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


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[0] == column for r in conn.execute("SELECT name FROM pragma_table_info(?)", (table,)))


def ensure_schema2(conn: sqlite3.Connection) -> None:
    """Add the schema-2 columns to the old tables when they are missing (repeatable). depot_positions is rebuilt by db_migrate, not here."""
    for table, column, sql in _NEW_COLUMNS:
        if not has_column(conn, table, column):
            conn.execute(sql)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookings_account ON bookings(account_id, date)")


def schema_version(conn: sqlite3.Connection) -> int:
    """1 = the v1.18 shape (no sources / accounts in use), 2 = sources and accounts. Unreadable values count as 1."""
    try:
        return int(meta_get(conn, "schema_version") or 1)
    except ValueError:
        return 1


def _is_new(conn: sqlite3.Connection) -> bool:
    return not any(conn.execute(sql).fetchone() for sql in _HAS_DATA)


def init(conn: sqlite3.Connection) -> None:
    """Create missing tables. A new, empty database starts at schema 2; one that already holds data keeps its version until db_migrate upgrades it."""
    with transaction(conn):
        conn.executescript(SCHEMA)
        if conn.execute("SELECT 1 FROM meta WHERE k='schema_version'").fetchone() is None:
            if _is_new(conn):
                ensure_schema2(conn)
                meta_set(conn, "schema_version", str(SCHEMA_VERSION))
            else:
                meta_set(conn, "schema_version", "1")


def meta_get(conn: sqlite3.Connection, k: str, default: str | None = None) -> str | None:
    r = conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def meta_set(conn: sqlite3.Connection, k: str, v: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, v))

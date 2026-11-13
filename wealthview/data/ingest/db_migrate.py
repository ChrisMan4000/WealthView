"""WealthView database, part 5 (v1.19): the one-time upgrade of an older database (schema 1) to sources and accounts (schema 2).
Order: backup copy next to the database -> one transaction that creates the sources and accounts, links every existing row to its account and
rebuilds depot_positions -> schema_version 2. Any failure rolls everything back; the database then keeps working in the old shape and the
upgrade is tried again at the next start. Source folders are not touched. Standard library only."""
from __future__ import annotations
import os, sqlite3
from pathlib import Path
from typing import Any

from ...common.types.accounts import UpgradeReport
from . import db_accounts, db_schema
from .db_import import csv_pseudo_iban

BACKUP_NAME = "wealthview.db.pre-accounts.bak"
ORPHAN_NAME = "Imported bookings"        # holds rows whose folder is no longer known (no config, no profile)
_BANK_READERS = {"gls": "gls", "gls_depot": "gls", "paypal": "paypal", "csv": "csv"}       # profile source kind -> reader


def needs_upgrade(conn: sqlite3.Connection) -> bool:
    return db_schema.schema_version(conn) < 2


def _report(ok: bool, skipped: bool = False, error: str | None = None, sources: int = 0, accounts: int = 0, linked: int = 0) -> UpgradeReport:
    return UpgradeReport(ok=ok, skipped=skipped, sources=sources, accounts=accounts, bookings_linked=linked, error=error)


def _backup(conn: sqlite3.Connection, target: Path) -> None:
    """Copy the database to `target` (kept if it already exists: the first backup is the real pre-upgrade state)."""
    if target.exists():
        return
    part = target.with_name(target.name + ".part")
    part.unlink(missing_ok=True)                  # a half-written copy of an earlier, interrupted attempt
    dst = sqlite3.connect(str(part))
    try:
        conn.backup(dst)
    finally:
        dst.close()
    os.replace(part, target)


def _norm(folder: str) -> str:
    return os.path.normcase(os.path.abspath(folder))


def _folder_name(folder: str) -> str:
    return Path(folder.rstrip("/\\")).name or folder


def _make_sources(conn: sqlite3.Connection, cfg: dict[str, Any], profile_sources: list[dict[str, Any]], *, new_install: bool = False) -> dict[str, Any]:
    """Create the sources of the existing setup. Returns {'gls': id | None, 'paypal': id | None, 'csv': {pseudo iban: id}}.
    Upgrade (new_install False): only the folders config.json names become sources, because those are the folders the old version imported;
    profile.json only supplies the user's name for a folder, and sub-folders stay off - exactly the same files are read as before.
    New install: every folder of profile.json becomes a source as well, with sub-folders on."""
    found: dict[str, Any] = {"gls": None, "paypal": None, "csv": {}}
    seen: dict[tuple[str, str], int] = {}         # (reader, folder) -> source id
    names: dict[tuple[str, str], str] = {}        # (reader, folder) -> the user's name from profile.json
    coinbase_name = None
    profile: list[tuple[str, str, str, Any]] = []
    for s in profile_sources:
        if not isinstance(s, dict):
            continue
        kind, folder, entity = str(s.get("kind") or ""), s.get("folder"), str(s.get("entity") or "").strip()
        if kind == "coinbase":
            coinbase_name = entity or "Crypto"
        reader = _BANK_READERS.get(kind)
        if reader and isinstance(folder, str) and folder:
            profile.append((reader, folder, entity, s.get("mapping")))
            if entity:
                names.setdefault((reader, _norm(folder)), entity)

    def folder_source(reader: str, folder: str, entity: str, key: str, options: dict[str, Any]) -> None:
        k = (reader, _norm(folder))
        if k not in seen:
            seen[k] = db_accounts.add_source(conn, names.get(k) or entity or _folder_name(folder), "bank", "folder", folder=folder, reader=reader,
                                             options=dict(options, subfolders=new_install), legacy_key=key)
        if reader == "csv":
            found["csv"].setdefault(csv_pseudo_iban(entity), seen[k])
        elif found[reader] is None:
            found[reader] = seen[k]

    def options_for(reader: str, entity: str, mapping: Any) -> dict[str, Any]:
        # csv: the entity is kept as it was (even empty), because the account id of its rows is derived from it
        return {"include_parent": True} if reader == "gls" else {"mapping": mapping, "entity": entity} if reader == "csv" else {}

    if isinstance(cfg.get("gls_dir"), str) and cfg["gls_dir"]:
        folder_source("gls", cfg["gls_dir"], "", "cfg:gls_dir", options_for("gls", "", None))
    if isinstance(cfg.get("paypal_dir"), str) and cfg["paypal_dir"]:
        folder_source("paypal", cfg["paypal_dir"], "", "cfg:paypal_dir", {})
    raw = cfg.get("csv_sources")
    for sc in raw if isinstance(raw, list) else []:
        if isinstance(sc, dict) and isinstance(sc.get("folder"), str) and sc["folder"]:
            entity = str(sc.get("entity") or "")
            folder_source("csv", sc["folder"], entity, f"cfg:csv:{_norm(sc['folder'])}", options_for("csv", entity, sc.get("mapping")))
    if new_install:
        for reader, folder, entity, mapping in profile:
            folder_source(reader, folder, entity, f"profile:{reader}:{_norm(folder)}", options_for(reader, entity, mapping))
    if coinbase_name or conn.execute("SELECT 1 FROM snapshots WHERE scope='coin' LIMIT 1").fetchone():
        db_accounts.add_source(conn, coinbase_name or "Crypto", "crypto", "api", connector="coinbase", reader="coinbase", legacy_key="api:coinbase")
    return found


def _orphan(conn: sqlite3.Connection) -> int:
    return db_accounts.add_source(conn, ORPHAN_NAME, "bank", "manual", reader="none", legacy_key="orphan:bookings")


def _link_bookings(conn: sqlite3.Connection, found: dict[str, Any]) -> int:
    """Give every booking its account: one account per IBAN (rows without one share an 'unknown' account). Returns the number of linked rows."""
    linked = 0
    for (iban,) in conn.execute("SELECT DISTINCT COALESCE(iban,'') FROM bookings").fetchall():
        sid = found["csv"].get(iban) if iban.startswith("CSV-") else found["gls"]
        if sid is None:
            sid = _orphan(conn)
        newest = conn.execute("SELECT account FROM bookings WHERE COALESCE(iban,'')=? ORDER BY date DESC, id DESC LIMIT 1", (iban,)).fetchone()
        is_card = conn.execute("SELECT 1 FROM bookings WHERE COALESCE(iban,'')=? AND kind='card' LIMIT 1", (iban,)).fetchone()
        acc = db_accounts.account_for(conn, sid, iban, (newest[0] if newest else "") or "Account", "card" if is_card else "bank")
        linked += conn.execute("UPDATE bookings SET account_id=? WHERE COALESCE(iban,'')=?", (acc, iban)).rowcount
    return linked


def _link_paypal(conn: sqlite3.Connection, found: dict[str, Any]) -> None:
    if not conn.execute("SELECT 1 FROM paypal_tx LIMIT 1").fetchone():
        return
    sid = found["paypal"] if found["paypal"] is not None else _orphan(conn)
    name = conn.execute("SELECT name FROM sources WHERE id=?", (sid,)).fetchone()[0]
    conn.execute("UPDATE paypal_tx SET account_id=?", (db_accounts.account_for(conn, sid, "paypal", name, "bank"),))


def _rebuild_depot(conn: sqlite3.Connection, found: dict[str, Any]) -> None:
    """depot_positions gets account_id in its key (several depots can hold the same security on the same day)."""
    if db_schema.has_column(conn, "depot_positions", "account_id"):
        return
    acc = 0
    if conn.execute("SELECT 1 FROM depot_positions LIMIT 1").fetchone():
        sid = found["gls"] if found["gls"] is not None else _orphan(conn)
        acc = db_accounts.account_for(conn, sid, "depot", "Depot", "depot")
    conn.execute("ALTER TABLE depot_positions RENAME TO depot_positions_v1")
    conn.execute("CREATE TABLE depot_positions(account_id INTEGER NOT NULL DEFAULT 0, asof TEXT NOT NULL, wkn TEXT NOT NULL, name TEXT, qty REAL, "
                 "price REAL, value REAL, gain REAL, gain_pct REAL, file_id INTEGER, PRIMARY KEY(account_id, asof, wkn))")
    conn.execute("INSERT INTO depot_positions(account_id,asof,wkn,name,qty,price,value,gain,gain_pct,file_id) "
                 "SELECT ?,asof,wkn,name,qty,price,value,gain,gain_pct,file_id FROM depot_positions_v1", (acc,))
    conn.execute("DROP TABLE depot_positions_v1")


def upgrade(conn: sqlite3.Connection, db_path: str | Path, cfg: dict[str, Any], profile_sources: list[dict[str, Any]]) -> UpgradeReport:
    """Upgrade a schema-1 database in place. profile_sources = profile.json's [{kind, folder, entity, mapping}] (may be empty).
    Never raises for a database or file problem: ok False + error, and nothing is changed."""
    try:
        db_schema.init(conn)                          # the new, empty tables (a v1 database keeps its version)
        if not needs_upgrade(conn):
            return _report(True, skipped=True)
        _backup(conn, Path(db_path).with_name(BACKUP_NAME))
    except (sqlite3.Error, OSError) as e:
        return _report(False, error=str(e))
    try:
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")              # explicit: the table changes below must roll back together with the rows
        db_schema.ensure_schema2(conn)
        found = _make_sources(conn, cfg, profile_sources)
        linked = _link_bookings(conn, found)
        _link_paypal(conn, found)
        _rebuild_depot(conn, found)
        db_schema.meta_set(conn, "schema_version", "2")
        db_schema.meta_set(conn, SEEDED_KEY, "1")
        n_src = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        n_acc = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        conn.commit()
        return _report(True, sources=n_src, accounts=n_acc, linked=linked)
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as e:
        conn.rollback()
        return _report(False, error=str(e))


SEEDED_KEY = "sources_seeded"


def seed(conn: sqlite3.Connection, cfg: dict[str, Any], profile_sources: list[dict[str, Any]]) -> int:
    """For a schema-2 database that has no sources yet (a new install whose folders were written to profile.json / config.json by the installer):
    create the sources once, with sub-folders read. Returns how many were created; 0 when it ran before, or on the old shape."""
    if db_schema.schema_version(conn) < 2 or db_schema.meta_get(conn, SEEDED_KEY) or conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone():
        return 0
    with db_schema.transaction(conn):
        _make_sources(conn, cfg, profile_sources, new_install=True)
        db_schema.meta_set(conn, SEEDED_KEY, "1")
        return int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])

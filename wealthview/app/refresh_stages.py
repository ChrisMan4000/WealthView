"""Stages of the refresh that fill the RunContext: open and sync the database, read the bookings and the depot, save trades and the daily snapshot."""
from __future__ import annotations
import json, sqlite3
from ..common import config, safenet
from ..common.paths import data_path
from ..common.parsing import iso
from ..common.runcontext import RunContext, UNCHANGED, db_unchanged_note, run_stage, unchanged_note
from ..common.timeutil import now, today
from ..common.types.bookings import BookingRow, Coverage
from ..common.types.datajson import DataJson, DbBlock
from ..common.types.depot import Depot
from ..common.types.status import SyncReport
from ..data.finance import catrules
from ..data.finance.lots import parse_trades
from ..data.finance.positions import enrich_depot
from ..data.ingest.loaders import GLS_CACHE_NAME
from ..data.ingest import db_import, db_queries, db_schema, loaders


DB_ERRORS = (sqlite3.Error, OSError, ValueError, KeyError, TypeError)      # what a failing database read can raise


def has_data(conn: sqlite3.Connection) -> bool:
    """True when the database already holds bookings (so an unchanged folder signature means there is nothing to import)."""
    try:
        return bool(conn.execute("SELECT 1 FROM bookings LIMIT 1").fetchone())
    except sqlite3.Error:
        return False


def open_db(ctx: RunContext) -> tuple[sqlite3.Connection | None, SyncReport | None]:
    """(connection, sync report) - imports new files from the watched folders first. (None, None) if the database cannot be used."""
    try:
        conn = db_schema.connect(data_path(db_schema.DB_NAME))
        rep: SyncReport
        if has_data(conn) and not db_import.folders_changed(conn, config.load_config()):
            rep = dict(at=now().isoformat(timespec="seconds"), seen=0, unchanged=0, new_files=[], duplicate_files=[], errors=[],
                       new_bookings=0, new_paypal=0, new_depot=0, skipped=True)
            ctx.set_status("database", "ok", "no new or changed files" + UNCHANGED)
        else:
            rep = db_import.sync(conn, config.load_config())
        def seed_snapshots() -> None:
            hf = data_path("history.json")
            if hf.exists() and not conn.execute("SELECT 1 FROM snapshots LIMIT 1").fetchone():      # one-time import into an empty database
                db_queries.seed_snapshots_from_history(conn, json.loads(hf.read_text("utf-8-sig")))
        run_stage(ctx, "refresh_stages.open_db", seed_snapshots, None, errors=(OSError, ValueError, KeyError, TypeError, sqlite3.Error))
        return conn, rep
    except Exception as e:      # broad on purpose: the database is optional, the refresh falls back to reading the files
        safenet.log.warning("database not usable: %s", e)
        ctx.set_status("database", "warn", "database not usable, reading the files directly: " + str(e))
        return None, None


def load_category_rules(ctx: RunContext, conn: sqlite3.Connection | None) -> None:
    """Your saved category corrections (database) -> the classifier. A failure only warns: the built-in rules still work."""
    if conn is None:
        return
    run_stage(ctx, "refresh_stages.load_category_rules", lambda: catrules.load_rules_into_classifier(conn), None, status="database",
              msg="your category rules could not be loaded: ", errors=DB_ERRORS)


def record_snapshot(ctx: RunContext, conn: sqlite3.Connection | None, data: DataJson) -> None:
    """One record per day (the last refresh of the day wins): totals, asset classes, positions, coins."""
    if conn is None:
        return

    def save() -> None:
        t = data["totals"]
        depot, cb = data.get("depot"), data.get("crypto")
        items: list[tuple[str, str, float | None, float | None]] = [
            ("total", "gross", t.get("assets"), None), ("total", "net", t.get("net"), None),
            ("total", "net_after_tax", t.get("net_after_tax"), None), ("total", "liabilities", t.get("liabilities"), None)]
        items += [("class", g["k"], g["v"], None) for g in t.get("groups", [])]
        items += [("position", p["wkn"], p["value"], p["qty"]) for p in (depot["positions"] if depot else [])]
        items += [("coin", h["currency"], h.get("eur"), h.get("amount")) for h in (cb["holdings"] if cb else [])]
        db_queries.record_snapshot_rows(conn, today().isoformat(), items)
    run_stage(ctx, "refresh_stages.record_snapshot", save, None, status="database", msg="snapshot not saved: ", errors=(sqlite3.Error, KeyError, TypeError))


def _safe_counts(conn: sqlite3.Connection) -> dict[str, int | str | None]:
    try:
        return db_queries.counts(conn)
    except DB_ERRORS as exc:
        safenet.swallowed("refresh_stages.counts", exc)
        return {}


def db_block(conn: sqlite3.Connection | None, sync_rep: SyncReport | None, cov: list[Coverage]) -> DbBlock | None:
    """What the page shows about the database (System status / coverage)."""
    if conn is None:
        return None
    try:
        last = json.loads(db_schema.meta_get(conn, "last_import", "null") or "null")
    except (sqlite3.Error, ValueError, TypeError):
        last = None
    f = data_path(db_schema.DB_NAME)
    return DbBlock(file=db_schema.DB_NAME, size_kb=round(f.stat().st_size / 1024) if f.exists() else None, counts=_safe_counts(conn),
                sync=sync_rep, last_import=last, coverage=cov)


def load_rows(ctx: RunContext, conn: sqlite3.Connection | None) -> list[BookingRow]:
    """GLS bookings from the database (or the files as fallback); reports the 'gls' status.
    The database is the primary store. The CSV fallback (loaders.load_gls) is deliberate, for an unusable or empty database; it
    only looks at the GLS DATA folder, while db_import.watched_files also imports the older exports from the folder above it."""
    empty: list[BookingRow] = []
    rows = run_stage(ctx, "refresh_stages.load_gls_rows", lambda: db_queries.load_gls_rows(conn) if conn else empty, empty, status="database",
                     msg="bookings could not be read from the database, reading the files: ", errors=DB_ERRORS)
    if not rows:
        # explicit CSV fallback: the database is the primary store; the CSV scan is only used when it is unusable or empty
        safenet.log.warning("bookings: %s - reading the GLS CSV files directly", "database not usable" if conn is None else "database has no bookings")
        rows, _ = loaders.load_gls(ctx)
    ctx.set_status("gls", "ok" if rows else "off",
           f"{len(rows)} bookings, last {rows[0]['date']:%d.%m.%Y}" + (db_unchanged_note(ctx) if conn else unchanged_note(ctx, GLS_CACHE_NAME)) if rows else "no readable GLS bookings",
           asof=iso(rows[0]["date"]) if rows else None)
    return rows


def load_depot_with_trades(ctx: RunContext, rows: list[BookingRow]) -> Depot | None:
    """Depot with live quotes, plus the purchases read from the bank bookings (a failure only warns). Reads only - the
    caller saves the trades (see save_trades)."""
    depot = loaders.load_depot(ctx)
    if depot:
        enrich_depot(ctx, depot)

    def attach_trades() -> None:
        trades = parse_trades(rows)
        if depot:
            for p in depot["positions"]:
                p["trades"] = trades.get(p["wkn"], [])
            depot["trades_from"] = iso(min(r["date"] for r in rows)) if rows else None
            depot["n_trades"] = sum(len(p["trades"]) for p in depot["positions"])
    run_stage(ctx, "refresh_stages.load_depot_with_trades", attach_trades, None, status="trades", msg="could not read purchases from the bank bookings: ")
    return depot


def save_trades(ctx: RunContext, conn: sqlite3.Connection | None, rows: list[BookingRow]) -> None:
    """Stores the securities trades parsed from the bank bookings in the database (a failure only warns)."""
    if not conn:
        return
    run_stage(ctx, "refresh_stages.save_trades", lambda: db_queries.store_trades(conn, parse_trades(rows)), None, status="trades",
              msg="could not save purchases to the database: ")
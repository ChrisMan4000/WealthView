"""PayPal balance: newest balance from the database, or (fallback) from the 'Download*.csv' activity exports."""
from __future__ import annotations
from typing import Any
import csv, io
import datetime as dt
import sqlite3
from pathlib import Path

from ...common import safenet
from ...common.types.bookings import PaypalInfo
from ...common.runcontext import RunContext, unchanged_note, db_unchanged_note
from ...common.parse_cache import cached_parse
from ...common.parsing import iso, num, pdate, read_text, round2
from ...common.config import setting
from ...common.timeutil import today


# ((date, 'HH:MM:SS'), balance): the newest balance and when it was booked
PaypalBest = tuple[tuple[dt.date, str], float]


def paypal_best_from_db(conn: sqlite3.Connection) -> PaypalBest | None:
    """Newest PayPal balance in the database as ((date, 'HH:MM:SS'), balance) - same rule as the file scan: later row wins in the same second."""
    r = conn.execute("SELECT date, time, balance FROM paypal_tx WHERE balance IS NOT NULL ORDER BY date DESC, time DESC, id DESC LIMIT 1").fetchone()
    return ((dt.date.fromisoformat(r["date"]), r["time"] or ""), r["balance"]) if r else None


def _scan_paypal_files(files: list[Path]) -> dict[str, Any]:
    """Raw scan of the PayPal CSVs (fallback when the database is unusable): newest balance as [iso date, time, balance]."""
    best, errors = None, []
    for f in files:
        try:
            for r in csv.DictReader(io.StringIO(read_text(f))):
                dte = pdate(r.get("Datum"))
                bal = num(r.get("Guthaben"))
                if not dte or bal is None:
                    continue
                key = [dte.isoformat(), r.get("Uhrzeit") or ""]
                if best is None or key >= best[:2]:   # same second: the later row in the file is the newer balance
                    best = key + [bal]
        except (OSError, ValueError, csv.Error) as e:
            errors.append(f"{f.name}: {e}")
    return dict(best=best, errors=errors)


def load_paypal_preferring_db(ctx: RunContext, db_best: PaypalBest | None = None) -> PaypalInfo:
    info: PaypalInfo = dict(balance=None, asof=None, files=0)
    paypal_dir = setting("paypal_dir")
    if not paypal_dir:
        ctx.set_status("paypal", "off", "paypal_dir not set in config.json")
        return info
    d = Path(paypal_dir)
    try:
        entries = list(d.iterdir())
    except OSError as e:
        ctx.set_status("paypal", "off", f"folder not readable: {e}")
        return info
    files = [p for p in entries if p.suffix.lower() == ".csv" and p.name.lower().startswith("download")]
    info["files"] = len(files)
    best = db_best
    unreadable = ""         # added to the status text below, so a file that could not be read stays visible next to a good one
    if db_best is None and files:
        raw = cached_parse(ctx, "paypal_best", files, _scan_paypal_files)
        for msg in raw["errors"]:
            safenet.log.warning("PayPal file not readable: %s", msg)
        if raw["errors"]:
            unreadable = f" ({len(raw['errors'])} file(s) unreadable)"
        if raw["best"]:
            best = ((dt.date.fromisoformat(raw["best"][0]), raw["best"][1]), raw["best"][2])
    if best and (today() - best[0][0]).days > 365:
        ctx.set_status("paypal", "warn", f"newest balance is from {best[0][0]:%d.%m.%Y} - too old to use" + unreadable, asof=iso(best[0][0]))
        ctx.add_alert("info", "PayPal: only exports up to " + f"{best[0][0]:%Y} found - download a current 'Download.CSV' activity export to include the balance.")
        info["asof"] = iso(best[0][0])
    elif best:
        info["balance"] = round2(best[1])
        info["asof"] = iso(best[0][0])
        ctx.set_status("paypal", "ok", f"balance as of {best[0][0]:%d.%m.%Y}" + (unchanged_note(ctx, "paypal_best") if db_best is None else db_unchanged_note(ctx)) + unreadable, asof=iso(best[0][0]))
        if (today() - best[0][0]).days > 45:
            ctx.add_alert("info", "PayPal activity export is old - download a fresh one for an up-to-date balance.")
    else:
        ctx.set_status("paypal", "warn", "no readable activity CSV with a balance column" + unreadable)
    return info

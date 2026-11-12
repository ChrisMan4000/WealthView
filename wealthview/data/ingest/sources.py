"""Which sources need fresh data? Pure rule (update_status) plus a collector that reads the newest data date per source
from the SQLite database and the World Fund loader result. Coinbase is live and therefore never listed."""
from __future__ import annotations
import calendar
import datetime as dt
import re
from ...common import safenet
import sqlite3
from typing import Any, NamedTuple

from ...common import config
from ...common.types.datajson import ReminderItem, Reminders, WorldFund

SLACK_DAYS = 3             # weekends / holidays: an export up to 3 days before month end still counts as complete
WORLDFUND_MAX_AGE = 135    # quarterly report: due when the newest one is older than this many days

KIND_LABEL = {"giro": "GLS Giro", "tages": "GLS Tagesgeld", "card": "GLS Credit card", "shares": "GLS Bank shares"}   # as in 'Accounts & sources'

# key, display name, what to download, config folder key, schedule, sub-folder inside the configured folder, file name pattern, where to get it
# (checked against db_import.watched_files and loaders.load_gls / load_depot / load_worldfund: GLS Umsaetze + Depotbestand CSVs both go into the GLS DATA
# folder, PayPal exports named Download*.CSV into the PayPal folder, World Fund report PDFs into the 'Fund I Reporting' sub-folder)
class Family(NamedTuple):
    key: str
    name: str
    what: str
    folder_key: str
    schedule: str
    sub: str
    pattern: str
    where: str


FAMILIES = [
    Family("gls", "GLS Bank", "GLS Umsaetze CSV export, one file per account", "gls_dir", "monthly", "", "Umsaetze_*.csv", "GLS Bank online banking"),
    Family("depot", "GLS Depot", "GLS Depotbestand CSV export of the securities account", "gls_dir", "monthly", "", "Depotbestand_*.csv", "GLS Bank online banking"),
    Family("paypal", "PayPal", "PayPal activity export as CSV (file name starts with Download)", "paypal_dir", "monthly", "", "Download*.CSV", "PayPal website"),
    Family("worldfund", "World Fund", "World Fund quarterly report PDF", "worldfund_dir", "quarterly", "Fund I Reporting",
     "*Qn YYYY*.pdf, e.g. Fund I Q2 2026 Reporting.pdf", "the fund's quarterly investor report"),
]


def folder_path(cfg: dict[str, Any] | None, folder_key: str, sub: str = "") -> str:
    """The real folder for a source: the config value (as config.load_config() returns it) plus the sub-folder; '' when not configured."""
    base = str((cfg or {}).get(folder_key) or "")
    if not base:
        return ""
    if not sub:
        return base
    return base.rstrip("\\/") + ("\\" if "\\" in base else "/") + sub


def last_day_prev_month(today: dt.date) -> dt.date:
    return today.replace(day=1) - dt.timedelta(days=1)


def update_status(today: dt.date, latest: dict[str, Any], extra: dict[str, ReminderItem] | None = None, cfg: dict[str, Any] | None = None) -> Reminders:
    """latest = {'gls'|'depot'|'paypal'|'worldfund': date or None}. Monthly sources are due when their newest data is older than
    the last day of the previous month (minus SLACK_DAYS); World Fund when older than WORLDFUND_MAX_AGE days; no data at all = due.
    cfg (the loaded config) supplies the real upload folder of each source."""
    cutoff = last_day_prev_month(today) - dt.timedelta(days=SLACK_DAYS)
    items: list[ReminderItem] = []
    for fam in FAMILIES:
        d = latest.get(fam.key)
        if d is None:
            due = True
        elif fam.schedule == "monthly":
            due = d < cutoff
        else:
            due = (today - d).days > WORLDFUND_MAX_AGE
        item = ReminderItem(key=fam.key, source=fam.name, what_to_download=fam.what, where=fam.where, folder_key=fam.folder_key,
                    folder=folder_path(cfg, fam.folder_key, fam.sub), pattern=fam.pattern, schedule=fam.schedule,
                    latest=d.isoformat() if d else None, due=due, days_old=(today - d).days if d else None)
        if extra and extra.get(fam.key):
            item.update(extra[fam.key])
        items.append(item)
    return Reminders(month=today.strftime("%Y-%m"), any_due=any(i["due"] for i in items), items=items)


def quarter_end(year: int, q: int) -> dt.date:
    m = q * 3
    return dt.date(year, m, calendar.monthrange(year, m)[1])


def worldfund_latest(wf: WorldFund | None) -> dt.date | None:
    """End date of the newest World Fund quarter the loader knows: the stored report or a newer PDF found in the folder."""
    if not wf:
        return None
    best = None
    try:
        best = (int(wf["report_year"]), int(wf["report_q"]))
    except (KeyError, TypeError, ValueError) as exc:      # no usable report year/quarter in the record
        safenet.swallowed("sources.worldfund_report", exc)
    m = re.search(r"Q([1-4])\s*(20\d\d)", str(wf.get("newest_report_file") or ""))
    if m and (best is None or (int(m.group(2)), int(m.group(1))) > best):
        best = (int(m.group(2)), int(m.group(1)))
    return quarter_end(*best) if best else None


def _max_date(conn: sqlite3.Connection, sql: str) -> dt.date | None:
    try:
        r = conn.execute(sql).fetchone()
        return dt.date.fromisoformat(r[0]) if r and r[0] else None
    except (sqlite3.Error, ValueError, TypeError) as exc:
        safenet.swallowed("sources._max_date", exc)
        return None


def collect(conn: sqlite3.Connection | None, wf: WorldFund | None, today: dt.date) -> Reminders:
    """The data['reminders'] block. conn may be None (database unusable): then only World Fund is known."""
    latest: dict = {"worldfund": worldfund_latest(wf)}
    extra: dict[str, ReminderItem] = {}
    if conn is not None:
        latest["gls"] = _max_date(conn, "SELECT MAX(date) FROM bookings")
        latest["depot"] = _max_date(conn, "SELECT MAX(asof) FROM depot_positions")
        latest["paypal"] = _max_date(conn, "SELECT MAX(date) FROM paypal_tx")
        try:
            accts = [dict(name=KIND_LABEL.get(r[0], r[1] or r[0] or "account"), last=r[2])
                     for r in conn.execute("SELECT MAX(kind), MAX(account), MAX(date) FROM bookings GROUP BY iban ORDER BY 3 DESC")]
            extra["gls"] = ReminderItem(accounts=accts)
        except sqlite3.Error as exc:      # the optional per-account list stays empty
            safenet.swallowed("sources.gather", exc)
    return update_status(today, latest, extra, config.load_config())

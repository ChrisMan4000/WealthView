"""Data-gap detection - the one home of gap logic and gap alert texts: days where the running account balance does not follow from the bookings,
stale exports, and months without any booking (from db_queries.coverage())."""
from __future__ import annotations
from collections import defaultdict

import datetime as dt

from ..common.timeutil import today
from ..common.types.bookings import CASH_KINDS, BookingRow, Coverage
from ..common.types.depot import Depot
from ..common.types.status import Level

# ------------------------------------------------------ data gap detection
def _balance_gaps(rs: list[BookingRow]) -> list[tuple[dt.date, dt.date, float]]:
    """days where the running balance does not follow from the previous day's balance and the bookings: [(from, to, unexplained EUR)]"""
    days: defaultdict[dt.date, list[BookingRow]] = defaultdict(list)
    for r in rs:
        days[r["date"]].append(r)
    prev: float | None = None
    prevd: dt.date | None = None
    gaps: list[tuple[dt.date, dt.date, float]] = []
    for d in sorted(days):
        saldi = [x["balance"] for x in days[d] if x["balance"] is not None]       # a booking without a balance cannot anchor the check
        if not saldi:
            continue
        s = sum(x["amount"] for x in days[d])
        close = None
        if prev is not None and prevd is not None:
            exp = prev + s
            hit = [v for v in saldi if abs(v - exp) < 0.02]
            if hit:
                close = hit[0]
            elif abs(saldi[0] - exp) > 0.5:
                gaps.append((prevd, d, saldi[0] - exp))
        prev = close if close is not None else saldi[0]
        prevd = d
    return gaps


def _merge_gaps(gaps: list[tuple[dt.date, dt.date, float]]) -> list[tuple[dt.date, dt.date, float]]:
    """gaps less than a week apart are one gap"""
    merged: list[tuple[dt.date, dt.date, float]] = []
    for a, b, diff in gaps:
        if merged and (a - merged[-1][1]).days <= 7:
            merged[-1] = (merged[-1][0], b, merged[-1][2] + diff)
        else:
            merged.append((a, b, diff))
    return merged


def data_gaps(rows: list[BookingRow], depot: Depot | None) -> list[tuple[Level, str]]:
    alerts: list[tuple[Level, str]] = []
    by: defaultdict[str, list[BookingRow]] = defaultdict(list)
    for r in rows:
        by[r["iban"]].append(r)
    for rs in by.values():
        kind, name = rs[0]["kind"], rs[0]["account"]
        if kind not in CASH_KINDS:
            continue
        for a, b, diff in _merge_gaps(_balance_gaps(rs))[-4:]:
            alerts.append(("warn", f"DATA GAP in {name}: bookings seem to be missing between {a:%d.%m.%Y} and {b:%d.%m.%Y} (about {abs(diff):,.0f} EUR unexplained). Download that period from GLS."))
        last = max(r["date"] for r in rs)
        if kind == "giro" and (today() - last).days > 14:
            alerts.append(("warn", f"DATA GAP: newest {name} booking is from {last:%d.%m.%Y} ({(today() - last).days} days ago) - download a fresh export."))
    if depot and (depot.get("age_days") or 0) > 7:
        alerts.append(("warn", f"DATA GAP: the depot export is {depot['age_days']} days old - download a new 'Depotbestand' file."))
    return alerts


def gap_messages(cov: list[Coverage]) -> list[tuple[Level, str]]:
    msgs: list[tuple[Level, str]] = []
    for c in cov:
        if c["gap_months"]:
            g = c["gap_months"]
            txt = ", ".join(g[:6]) + (" ..." if len(g) > 6 else "")
            msgs.append(("warn", f"{c['account'] or c['iban']}: no bookings in {len(g)} month(s) between {c['first'][:7]} and {c['last'][:7]} ({txt}) - an export is probably missing."))
    return msgs

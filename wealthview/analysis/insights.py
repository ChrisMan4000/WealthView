"""
Insights that get better the longer WealthView runs (v1.08). Pure functions on the database snapshots, the monthly flows and
the spending rows - no network. Every block says how much history it rests on (`len` / `have_days`) and stays `ready: False`
with a plain reason until there is enough, instead of showing an invented number.
"""
from __future__ import annotations
from typing import Any
from collections.abc import Mapping
import calendar
import sqlite3
import datetime as dt
from statistics import median

from ..common.timeutil import month_key
from ..common.types.bookings import FLOW_KINDS, BookingRow, Coverage, FlowModel, SpendingRow
from ..common.types.datajson import Insights

NEED_DAYS = 28            # recorded history needed before "saved vs market" is shown


def eur(v: float) -> str:
    """12345.6 -> '12.346 €' (the format the page's blur rule recognises)."""
    return f"{round(abs(v)):,}".replace(",", ".") + " €"


def sgn_eur(v: float) -> str:
    return ("+" if v >= 0 else "-") + eur(v)


def pct_s(p: float) -> str:
    return ("+" if p >= 0 else "-") + f"{abs(p):.1f}".replace(".", ",") + " %"


# ------------------------------------------------------------------ recorded history
def snapshot_series(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    days: dict[str, dict[str, Any]] = {}
    for r in conn.execute("SELECT day, scope, key, value FROM snapshots WHERE scope IN ('total','class') ORDER BY day"):
        d = days.setdefault(r["day"], dict(classes={}))
        if r["scope"] == "total":
            d[r["key"]] = r["value"]
        else:
            d["classes"][r["key"]] = r["value"]
    return days


def recorded_curve(days: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ds = sorted(days)
    keys = sorted({k for d in days.values() for k in d["classes"]})
    return dict(days=ds, gross=[days[d].get("gross") for d in ds], net=[days[d].get("net") for d in ds],
                classes={k: [days[d]["classes"].get(k) for d in ds] for k in keys}, n_days=len(ds), first=ds[0] if ds else None)


def period_changes(days: dict[str, dict[str, Any]], today: dt.date, spans: tuple[tuple[int, str], ...] = ((7, "7 days"), (30, "30 days"), (90, "3 months"), (365, "12 months"))) -> list[dict[str, Any]]:
    ds = sorted(days)
    if len(ds) < 2:
        return []
    last = ds[-1]
    out: list[dict[str, Any]] = []
    partial_done = False
    for L, label in spans:
        target = (today - dt.timedelta(days=L)).isoformat()
        cand = [d for d in ds if d <= target]
        partial = not cand
        base = cand[-1] if cand else ds[0]
        if base == last:
            continue
        if partial:
            if partial_done:
                continue
            partial_done = True
        a, b = days[base], days[last]
        ch: dict[str, Any] = dict(label=label, days=L, base=base, last=last, span_days=(dt.date.fromisoformat(last) - dt.date.fromisoformat(base)).days, partial=partial)
        if a.get("gross") and b.get("gross") is not None:
            ch["gross"] = b["gross"] - a["gross"]
            ch["gross_pct"] = ch["gross"] / a["gross"] * 100
        ch["classes"] = {k: b["classes"][k] - a["classes"][k] for k in b["classes"] if k in a["classes"]}
        out.append(ch)
    return out


def saved_vs_market(days: dict[str, dict[str, Any]], flows: FlowModel | None, last_booking: str | None) -> dict[str, Any]:
    """Split the change of gross assets between the first and last recorded day into 'saved' (income - expenses of those days, prorated
    from the monthly flows) and 'market & other' (the rest). An estimate; needs NEED_DAYS of recorded history.
    """
    ds = sorted(days)
    have = (dt.date.fromisoformat(ds[-1]) - dt.date.fromisoformat(ds[0])).days if len(ds) >= 2 else 0
    base = dict(ready=False, have_days=have, need_days=NEED_DAYS, basis="estimate")
    if have < NEED_DAYS or not flows or days[ds[0]].get("gross") is None or days[ds[-1]].get("gross") is None:
        return base
    d0, d1 = dt.date.fromisoformat(ds[0]), dt.date.fromisoformat(ds[-1])
    lb = dt.date.fromisoformat(last_booking) if last_booking else d1
    end = min(d1, lb)
    saved = 0.0
    for i, m in enumerate(flows["months"]):
        y, mo = int(m[:4]), int(m[5:7])
        ms, me = dt.date(y, mo, 1), dt.date(y, mo, calendar.monthrange(y, mo)[1])
        data_end = min(me, lb)                                    # the days of this month the bookings really cover
        mdays = (data_end - ms).days + 1
        ov = (min(end, data_end) - max(d0, ms)).days + 1
        if ov <= 0 or mdays <= 0:
            continue
        saved += (flows["income"][i] - flows["expense"][i]) * min(1.0, ov / mdays)
    delta = days[ds[-1]]["gross"] - days[ds[0]]["gross"]
    return dict(base, ready=True, frm=ds[0], to=ds[-1], delta=delta, saved=saved, market=delta - saved)


# ------------------------------------------------------------------ bookings based
def _full_months(months: list[str], today: dt.date) -> int:
    return len(months) - (1 if months and months[-1] == month_key(today) else 0)


def spend_vs_norm(flows: FlowModel | None, today: dt.date, min_hist: int = 6) -> dict[str, Any]:
    if not flows:
        return dict(ready=False, reason="no bookings")
    n = _full_months(flows["months"], today)
    if n < min_hist + 1:
        return dict(ready=False, reason=f"needs {min_hist + 1} full months of bookings (have {n})", len=n)
    i = n - 1
    items: list[dict[str, Any]] = []
    for cat, s in flows["cats"].items():
        hist = s[max(0, i - 12):i]
        if len(hist) < min_hist:
            continue
        norm, val = median(hist), s[i]
        delta = val - norm
        if abs(delta) >= 50 and (norm == 0 or abs(delta) / norm >= 0.25):
            items.append(dict(cat=cat, value=val, norm=norm, delta=delta, pct=(delta / norm * 100) if norm else None))
    items.sort(key=lambda x: -abs(x["delta"]))
    return dict(ready=True, month=flows["months"][i], items=items[:6], len=n, basis="bookings")


def yoy(flows: FlowModel | None, today: dt.date) -> dict[str, Any]:
    if not flows:
        return dict(ready=False, reason="no bookings")
    n = _full_months(flows["months"], today)
    if n < 24:
        return dict(ready=False, reason=f"needs 24 full months of bookings (have {n})", len=n)
    def tot(a: int, b: int) -> dict[str, float]:
        inc, exp = sum(flows["income"][a:b]), sum(flows["expense"][a:b])
        return dict(income=inc, expense=exp, saved=inc - exp)
    now, prev = tot(n - 12, n), tot(n - 24, n - 12)
    ch = {k: ((now[k] - prev[k]) / abs(prev[k]) * 100) if prev[k] else None for k in now}
    return dict(ready=True, now=now, prev=prev, change_pct=ch, to=flows["months"][n - 1], len=n, basis="bookings")


def _merchant_months(spend: list[SpendingRow] | None, cur: str) -> tuple[dict[str, dict[str, float]], set[str]]:
    """spending per merchant and month for the full months before `cur` -> (merchant -> {month: EUR}, months seen)"""
    per: dict[str, dict[str, float]] = {}
    months: set[str] = set()
    for r in spend or []:
        m = str(r["date"])[:7]
        if m >= cur:
            continue
        months.add(m)
        per.setdefault(r["merchant"], {})
        per[r["merchant"]][m] = per[r["merchant"]].get(m, 0.0) + abs(r["amount"])
    return per, months


def _avg_months(per: dict[str, dict[str, float]], ms: list[str], n: str, lo: int, hi: int) -> float | None:
    vals = [per[n][m] for m in ms[lo:hi] if m in per[n]]
    return sum(vals) / len(vals) if vals else None


def _creep_and_new(per: dict[str, dict[str, float]], ms: list[str], rec: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """recurring merchants whose price rose against a year ago (creep) and those that did not exist then (new)"""
    creep: list[dict[str, Any]] = []
    new: list[dict[str, Any]] = []
    for n in rec:
        now = _avg_months(per, ms, n, len(ms) - 3, len(ms))
        was = _avg_months(per, ms, n, len(ms) - 15, len(ms) - 12) if len(ms) >= 15 else None
        if now is None:
            continue
        if was is None and len(ms) >= 15:
            new.append(dict(n=n, now=now))
        elif was and now >= was * 1.05 and now - was >= 1:
            creep.append(dict(n=n, now=now, was=was, pct=(now / was - 1) * 100))
    creep.sort(key=lambda x: -(x["now"] - x["was"]))
    new.sort(key=lambda x: -x["now"])
    return creep, new


def recurring_trend(spend: list[SpendingRow] | None, today: dt.date, recent: int = 6) -> dict[str, Any]:
    """Merchants that show up nearly every month (subscriptions, rent, insurance ...): their monthly total over time and price creep."""
    per, months = _merchant_months(spend, month_key(today))
    ms = sorted(months)
    if len(ms) < recent + 1:
        return dict(ready=False, reason=f"needs {recent + 1} full months of bookings (have {len(ms)})", len=len(ms))
    last_n = ms[-recent:]
    rec = [n for n, d in per.items() if sum(1 for m in last_n if m in d) >= recent - 1]
    span = ms[-24:]
    series = [dict(m=m, v=sum(per[n].get(m, 0.0) for n in rec)) for m in span]
    creep, new = _creep_and_new(per, ms, rec)
    now_total = sum(_avg_months(per, ms, n, len(ms) - 3, len(ms)) or 0 for n in rec)
    ago_total = sum(_avg_months(per, ms, n, len(ms) - 15, len(ms) - 12) or 0 for n in rec) if len(ms) >= 15 else None
    return dict(ready=True, series=series, now=now_total, ago=ago_total, creep=creep[:5], new=new[:5], n=len(rec), len=len(ms), basis="bookings")


# ------------------------------------------------------------------ digest
def _digest_change(ch: list[dict[str, Any]], curve: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    if ch:
        c = next((x for x in ch if x["days"] == 30 and not x["partial"]), None) or ch[-1]
        span = f"the last {c['label']}" if not c["partial"] else f"{c['span_days']} day(s) since {c['base']}"
        if c.get("gross") is not None:
            out.append(dict(l="info", t=f"Gross assets {sgn_eur(c['gross'])} ({pct_s(c['gross_pct'])}) in {span}",
                            x="Recorded by WealthView on each refresh (real values, not a back-cast)." + ("" if not c["partial"] else " History is still short, so this covers only the days recorded so far.")))
        cl = sorted(c["classes"].items(), key=lambda kv: -abs(kv[1]))
        if cl and abs(cl[0][1]) >= 500:
            out.append(dict(l="info", t=f"Biggest mover: {cl[0][0]} {sgn_eur(cl[0][1])} in {span}", x="Change of the asset-class value between the two recorded days: " + ", ".join(f"{k} {sgn_eur(v)}" for k, v in cl[:5]) + "."))
    elif curve and curve["n_days"] < 2:
        out.append(dict(l="info", t="Real history has just started", x="WealthView now saves one record per day. The 'Over time' box fills with real values (not estimates) and gets richer every week."))
    return out


def _digest_spending(sp: dict[str, Any]) -> list[dict[str, Any]]:
    if not (sp.get("ready") and sp["items"]):
        return []
    i = sp["items"][0]
    return [dict(l="idea" if i["delta"] > 0 else "info", t=f"{i['cat']}: {eur(i['value'])} in {sp['month']}, usually {eur(i['norm'])}",
                 x=("That is " + pct_s(i["pct"]) + " against your own 12-month median. " if i["pct"] is not None else "") + "Other categories off their norm: " + (", ".join(f"{x['cat']} {sgn_eur(x['delta'])}" for x in sp["items"][1:4]) or "none") + ".")]


def _digest_recurring(rec: dict[str, Any]) -> list[dict[str, Any]]:
    if not (rec.get("ready") and rec["creep"]):
        return []
    c = rec["creep"][0]
    return [dict(l="idea", t=f"Recurring cost grew: {c['n']} {eur(c['was'])} -> {eur(c['now'])} a month ({pct_s(c['pct'])})", x=f"{rec['n']} recurring payments cost about {eur(rec['now'])} a month now" + (f", {eur(rec['ago'])} a year ago." if rec.get("ago") else "."))]


def digest(ch: list[dict[str, Any]], svm: dict[str, Any], sp: dict[str, Any], rec: dict[str, Any], curve: dict[str, Any], cov: list[Coverage]) -> list[dict[str, Any]]:
    out = _digest_change(ch, curve)
    if svm.get("ready"):
        out.append(dict(l="info", t=f"Since {svm['frm']}: saved about {sgn_eur(svm['saved'])}, market & other {sgn_eur(svm['market'])}",
                        x=f"Gross assets changed by {sgn_eur(svm['delta'])}. The savings part is income minus spending from your bookings (estimate); the rest is price moves, valuations and other effects."))
    out += _digest_spending(sp)
    out += _digest_recurring(rec)
    for c in cov or []:
        if c.get("kind") in FLOW_KINDS and c.get("age_days", 0) > 35:
            out.append(dict(l="warn", t=f"{c['account'] or 'Account'}: newest booking is {c['age_days']} days old", x="Download a fresh Umsaetze export into the GLS DATA folder - WealthView imports it by itself."))
    return out


# ------------------------------------------------------------------ everything
def build(conn: sqlite3.Connection, data: Mapping[str, Any], rows: list[BookingRow], today: dt.date, spend: list[SpendingRow] | None = None) -> Insights:
    days = snapshot_series(conn)
    flows = data.get("flows")
    last_b = max((r["date"] for r in rows), default=None) if rows else None
    cov = (data.get("db") or {}).get("coverage") or []
    ch = period_changes(days, today)
    svm = saved_vs_market(days, flows, last_b.isoformat() if last_b else None)
    sp = spend_vs_norm(flows, today)
    yy = yoy(flows, today)
    rec = recurring_trend(spend, today)
    curve = recorded_curve(days)
    return Insights(version=1, curve=curve, changes=ch, saved_vs_market=svm, spend_vs_norm=sp, yoy=yy, recurring=rec,
                digest=digest(ch, svm, sp, rec, curve, cov))

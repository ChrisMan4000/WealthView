"""
Unusual bookings: four simple, explainable rules over the spending history.
  spike         far larger than the usual amount of that merchant (or of the category when the merchant is new)
  new_merchant  first booking ever from a merchant and a large amount (not during the first weeks of data)
  duplicate     same merchant and same amount again within a few days
  price_rise    a monthly payment that suddenly costs >= 5 % more
Rows: {date: ISO, merchant, amount (negative = spending), category}. Income and transfers are never flagged.
"""
from __future__ import annotations
from typing import Any
from collections.abc import Sequence
from ..common.types.bookings import SpendingRow
from ..common.types.datajson import UnusualFinding
import datetime as dt
from statistics import median
from ..common.config import DEFAULTS

_SKIP_CATEGORIES = {"transfer", "transfers", "investment", "investments", "umbuchung", "internal"}


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = dict(DEFAULTS["unusual"])
    out.update(cfg or {})
    return out


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def _eur(x: float) -> str:
    return ("%.2f" % x).rstrip("0").rstrip(".")


def _check_spike(c: dict[str, Any], hist: list[SpendingRow], cat_hist: list[SpendingRow], amt: float) -> tuple[str, str] | None:
    """1) spike: against the merchant's history, else the category's"""
    if len(hist) >= c["min_history"]:
        pool, label, need = hist, "this merchant", c["min_history"]
    else:
        pool, label, need = cat_hist, "this category", c["min_history"] * 2
    if len(pool) >= need and amt >= c["spike_min_eur"]:
        amts = [abs(h["amount"]) for h in pool]
        med = median(amts)
        mad = median([abs(a - med) for a in amts])
        if amt > max(3 * med, med + c["spike_mad"] * mad):
            return "spike", "%.1fx the usual %s EUR for %s" % (amt / med, _eur(med), label)
    return None


def _check_new_merchant(c: dict[str, Any], hist: list[SpendingRow], amt: float, day: dt.date, start: dt.date) -> tuple[str, str] | None:
    """2) new merchant with a large amount, after the warm-up weeks of the data set"""
    if not hist and amt >= c["new_merchant_eur"] and (day - start).days >= c["warmup_days"]:
        return "new_merchant", "first booking from this merchant"
    return None


def _check_duplicate(c: dict[str, Any], hist: list[SpendingRow], amt: float, day: dt.date) -> tuple[str, str] | None:
    """3) duplicate: same amount again within a few days"""
    if amt >= c["dup_min_eur"]:
        for h in reversed(hist):
            gap = (day - _d(h["date"])).days
            if gap > c["dup_days"]:
                break
            if abs(abs(h["amount"]) - amt) < 0.005:
                return "duplicate", "same amount %d day(s) after %s" % (gap, str(h["date"])[:10])
    return None


def _check_price_rise(c: dict[str, Any], hist: list[SpendingRow], r: SpendingRow, amt: float) -> tuple[str, str] | None:
    """4) price rise on a stable monthly payment (3 earlier monthly bookings, then a >= rise_pct step)"""
    if len(hist) >= 3:
        last = hist[-3:] + [r]
        gaps = [(_d(b["date"]) - _d(a["date"])).days for a, b in zip(last, last[1:])]
        prev = [abs(h["amount"]) for h in last[:3]]
        if all(25 <= g <= 35 for g in gaps) and min(prev) > 0 and max(prev) / min(prev) <= 1.02:
            rise = (amt / prev[-1] - 1) * 100
            if rise >= c["rise_pct"]:
                return "price_rise", "price up %.1f %% (%s -> %s EUR)" % (rise, _eur(prev[-1]), _eur(amt))
    return None


def find_unusual(rows: Sequence[SpendingRow], today: str, cfg: dict[str, Any] | None = None) -> list[UnusualFinding]:
    c = _cfg(cfg)
    spend = [r for r in rows or [] if r.get("amount") is not None and r["amount"] < 0
             and str(r.get("category") or "").strip().lower() not in _SKIP_CATEGORIES]
    spend.sort(key=lambda r: str(r["date"]))
    if not spend:
        return []
    start = _d(spend[0]["date"])
    limit = _d(today) - dt.timedelta(days=c["lookback_days"])
    by_merchant: dict[str, list[SpendingRow]] = {}
    by_category: dict[str | None, list[SpendingRow]] = {}
    out: list[UnusualFinding] = []
    for r in spend:
        m, cat, day, amt = str(r["merchant"]).strip().lower(), r.get("category"), _d(r["date"]), abs(r["amount"])
        hist = by_merchant.setdefault(m, [])
        cat_hist = by_category.setdefault(cat, [])
        found = [f for f in (_check_spike(c, hist, cat_hist, amt), _check_new_merchant(c, hist, amt, day, start),
                             _check_duplicate(c, hist, amt, day), _check_price_rise(c, hist, r, amt)) if f]
        hist.append(r)
        cat_hist.append(r)
        if found and day >= limit:
            out.append(UnusualFinding(date=str(r["date"])[:10], merchant=r["merchant"], amount=r["amount"],
                                      reasons=[f[0] for f in found], detail="; ".join(f[1] for f in found)))
    out.sort(key=lambda x: x["date"], reverse=True)
    return out

"""Data for the category-correction pop-up (v1.15): the merchants you spent money at, their category and a few recent bookings each.
Reads the database, runs the classifier with your saved rules, returns plain dicts. Writes nothing."""
from __future__ import annotations
import sqlite3
from collections import Counter, defaultdict
from typing import Any
from ..ingest import db_queries, db_rules
from . import categories
from .bookings import merchant_and_domain
from .categories import CAT_RULES, SONSTIGES, override_key
from .ownaccounts import OwnAccounts, cash_flow_events

MAX_MERCHANTS = 200
SAMPLES = 8
SIMILAR_AMOUNT_FACTOR = 5      # a booking more than 5x bigger or smaller than the corrected one counts as clearly different


def category_names(extra: list[str] | None = None) -> list[str]:
    """every category you can pick: the built-in ones, your own, and 'Sonstiges' (unsorted) last"""
    names = [c for c, _ in CAT_RULES]
    for c in (extra or []):
        if c and c not in names and c != SONSTIGES:
            names.append(c)
    return names + [SONSTIGES]


def load_rules_into_classifier(conn: sqlite3.Connection) -> None:
    rules, over = db_rules.load(conn)
    categories.set_user_rules(rules, over)


def overview(conn: sqlite3.Connection, only: str = "sonstiges", q: str = "") -> dict[str, Any]:
    """{categories, merchants: [{n, total, count, cat, mixed, last, samples: [{key, date, amount, purpose, cat, fixed}]}], rules, fixed}
    only = 'sonstiges' (merchants with unsorted bookings) | 'all'; q = part of a merchant name"""
    load_rules_into_classifier(conn)
    rows = db_queries.load_gls_rows(conn)
    over = db_rules.load(conn)[1]
    own = OwnAccounts(rows)
    agg: dict[str, dict[str, Any]] = {}
    for r, _mk, kind in cash_flow_events(rows, own):
        if kind in ("income", "invest"):
            continue
        name = merchant_and_domain(r)[0]
        a = agg.setdefault(name, dict(n=name, total=0.0, count=0, cats=Counter(), last=r["date"].isoformat(), unsorted=0.0, samples=[]))
        c = categories.classify(r)
        v = -r["amount"]
        a["total"] += v
        a["count"] += 1
        a["cats"][c] += v
        if c == SONSTIGES:
            a["unsorted"] += v
        if len(a["samples"]) < SAMPLES and (only != "sonstiges" or c == SONSTIGES):      # unsorted view: only the bookings still to fix, so fixed ones make room
            k = override_key(r)
            a["samples"].append(dict(key=k, date=r["date"].isoformat(), amount=round(v, 2), purpose=(r["counterparty"] + " · " + r["purpose"])[:110], cat=c, fixed=k in over))
    ql = q.strip().lower()
    out: list[dict[str, Any]] = []
    for a in agg.values():
        if ql and ql not in a["n"].lower():
            continue
        if only == "sonstiges" and a["unsorted"] <= 0:
            continue
        cats: Counter[str] = a["cats"]
        top = cats.most_common(1)[0][0]
        out.append(dict(n=a["n"], total=round(a["total"], 2), count=a["count"], cat=top, mixed=len(cats) > 1, unsorted=round(a["unsorted"], 2),
                        last=a["last"], samples=a["samples"]))
    out.sort(key=lambda m: -(m["unsorted"] if only == "sonstiges" else m["total"]))
    rules = db_rules.list_rules(conn)
    used = sorted({m["cat"] for m in out} | {r["category"] for r in rules})
    return dict(categories=category_names(used), merchants=out[:MAX_MERCHANTS], total_merchants=len(out), rules=rules, fixed=db_rules.count_overrides(conn))


def apply_to_similar(conn: sqlite3.Connection, key: str, category: str) -> dict[str, Any]:
    """After one booking was corrected: give the other bookings of the same merchant the same category, unless they are clearly different.
    Left alone: bookings you fixed yourself, bookings that were sorted into another category than the corrected one had, and amounts far off (5x).
    Saved as single-booking corrections, so each can be undone. Returns {applied: number of other bookings changed}."""
    load_rules_into_classifier(conn)
    rows = db_queries.load_gls_rows(conn)
    over = db_rules.load(conn)[1]
    events = [(r, categories.classify(r)) for r, _mk, kind in cash_flow_events(rows, OwnAccounts(rows)) if kind not in ("income", "invest")]
    hit = next(((r, c) for r, c in events if override_key(r) == key), None)
    if hit is None:
        return dict(applied=0)
    target, old_cat = hit
    name, base = merchant_and_domain(target)[0], abs(target["amount"])
    applied = 0
    for r, c in events:
        k = override_key(r)
        if k == key or k in over or c != old_cat or merchant_and_domain(r)[0] != name:
            continue
        amt = abs(r["amount"])
        if base > 0 and not (base / SIMILAR_AMOUNT_FACTOR <= amt <= base * SIMILAR_AMOUNT_FACTOR):
            continue
        db_rules.set_override(conn, k, category, name)
        applied += 1
    return dict(applied=applied)


def correct_booking(conn: sqlite3.Connection, key: str, category: str, name: str = "") -> dict[str, Any]:
    """Saves the correction of one booking and passes it on to the similar bookings of the same merchant (see apply_to_similar)."""
    res = apply_to_similar(conn, key, category)      # first: it needs the category the booking had before the correction
    db_rules.set_override(conn, key, category, name)
    return res

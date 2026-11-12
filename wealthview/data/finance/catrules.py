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
        if len(a["samples"]) < SAMPLES:
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

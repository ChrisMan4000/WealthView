"""Your category corrections in the database (v1.15): merchant / keyword rules (cat_rules) and corrections of single bookings (cat_overrides).
The classifier (finance/categories.py) uses them before its built-in rules. Standard library only."""
from __future__ import annotations
import sqlite3
import datetime as dt
from ...common.types.rules import RuleRow

MAX_NAME = 120
MAX_CAT = 40


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def load(conn: sqlite3.Connection) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    """(rules as (kind, pattern, category), {booking key: category}) for categories.set_user_rules"""
    rules = [(r["kind"], r["pattern"], r["category"]) for r in conn.execute("SELECT kind, pattern, category FROM cat_rules ORDER BY id")]
    over = {r["okey"]: r["category"] for r in conn.execute("SELECT okey, category FROM cat_overrides")}
    return rules, over


def list_rules(conn: sqlite3.Connection) -> list[RuleRow]:
    return [RuleRow(id=r["id"], kind=r["kind"], pattern=r["pattern"], category=r["category"], created=r["created"] or "")
            for r in conn.execute("SELECT id, kind, pattern, category, created FROM cat_rules ORDER BY category, pattern")]


def _clean(s: object, limit: int) -> str:
    return " ".join(str(s or "").split())[:limit]


def add_rule(conn: sqlite3.Connection, kind: str, pattern: object, category: object) -> None:
    kind = kind if kind in ("merchant", "text") else "merchant"
    p, c = _clean(pattern, MAX_NAME), _clean(category, MAX_CAT)
    if not p or not c:
        raise ValueError("a rule needs a name and a category")
    with conn:
        conn.execute("INSERT INTO cat_rules(kind, pattern, category, created) VALUES(?,?,?,?) "
                     "ON CONFLICT(kind, pattern) DO UPDATE SET category=excluded.category, created=excluded.created", (kind, p, c, _now()))


def delete_rule(conn: sqlite3.Connection, rule_id: object) -> None:
    with conn:
        conn.execute("DELETE FROM cat_rules WHERE id=?", (int(str(rule_id)),))


def set_override(conn: sqlite3.Connection, okey: object, category: object, label: object = "") -> None:
    k, c = _clean(okey, 40), _clean(category, MAX_CAT)
    if not k or not c:
        raise ValueError("a correction needs a booking and a category")
    with conn:
        conn.execute("INSERT OR REPLACE INTO cat_overrides(okey, category, label, created) VALUES(?,?,?,?)", (k, c, _clean(label, 160), _now()))


def delete_override(conn: sqlite3.Connection, okey: object) -> None:
    with conn:
        conn.execute("DELETE FROM cat_overrides WHERE okey=?", (_clean(okey, 40),))


def count_overrides(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM cat_overrides").fetchone()[0])

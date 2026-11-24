"""Grocery orders (Knuspr) in the database: tables, one-time import from an export file, and the read for the Groceries pop-up.
The export file is only a carrier: import it, then delete it. Nothing but the database keeps the data."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS groc_orders(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, total REAL, goods REAL, delivery REAL, tip REAL, deposit REAL, credits REAL, items INTEGER);
CREATE TABLE IF NOT EXISTS groc_items(order_id INTEGER NOT NULL, product_id INTEGER NOT NULL, qty REAL, eur REAL);
CREATE TABLE IF NOT EXISTS groc_products(id INTEGER PRIMARY KEY, name TEXT, img TEXT, cat TEXT, sub TEXT, size TEXT);
CREATE INDEX IF NOT EXISTS groc_items_o ON groc_items(order_id);
"""


def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def import_file(conn: sqlite3.Connection, path: str | Path) -> dict[str, int]:
    """Replace all grocery tables by the content of an export file ({orders, rows, products}); returns the row counts."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    ensure(conn)
    with conn:
        for t in ("groc_orders", "groc_items", "groc_products"):
            conn.execute(f"DELETE FROM {t}")
        conn.executemany("INSERT OR REPLACE INTO groc_orders VALUES(?,?,?,?,?,?,?,?,?)", d["orders"])
        conn.executemany("INSERT INTO groc_items VALUES(?,?,?,?)", d["rows"])
        conn.executemany("INSERT OR REPLACE INTO groc_products VALUES(?,?,?,?,?,?)",
                         [(int(k), *v[:5]) for k, v in d["products"].items()])
    return {"orders": len(d["orders"]), "items": len(d["rows"]), "products": len(d["products"])}


def overview(conn: sqlite3.Connection) -> dict[str, Any]:
    """Everything the pop-up needs, compact: orders, item rows and products (all aggregation happens in the page)."""
    ensure(conn)
    o = [list(r) for r in conn.execute("SELECT id,ts,total,goods,delivery,tip,deposit,credits,items FROM groc_orders ORDER BY ts")]
    if not o:
        return {"empty": True}
    r = [list(x) for x in conn.execute("SELECT order_id,product_id,qty,eur FROM groc_items")]
    p = {row[0]: row[1:] for row in conn.execute("SELECT id,name,img,cat,sub,size FROM groc_products")}
    return {"orders": o, "rows": r, "products": p}


def import_pending(conn: sqlite3.Connection, path: str | Path) -> dict[str, int] | None:
    """If the carrier file exists: import it into the tables, delete the file, return the counts (else None)."""
    f = Path(path)
    if not f.exists():
        return None
    counts = import_file(conn, f)
    f.unlink()
    return counts

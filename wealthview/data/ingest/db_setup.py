"""WealthView database, part 9 (v1.20): what the setup screen of the dashboard shows and changes - the places the data comes from (banks, investments,
crypto), the typed assets and balances, and the open questions. Plain dicts in and out; every failure the person can fix is a ValueError with a plain
sentence. Writes commit by themselves. Standard library only."""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any

from . import db_accounts, db_assets, db_questions
from .db_schema import SECTIONS, transaction

MAX_NAME = 80
ACTIONS = ("add", "rename", "folder", "subfolders", "active", "delete")


def _name(v: Any) -> str:
    n = " ".join(str(v or "").split())[:MAX_NAME]
    if not n:
        raise ValueError("please give it a name")
    return n


def _folder(v: Any) -> str:
    f = str(v or "").strip().strip('"')
    if not f:
        raise ValueError("please choose a folder")
    if not Path(f).is_dir():
        raise ValueError("this folder does not exist on this computer: " + f)
    return f


def _source(conn: sqlite3.Connection, sid: Any) -> db_accounts.SourceRow:
    for s in db_accounts.list_sources(conn, active_only=False):
        if s["id"] == sid and not s["options"].get("asset"):
            return s
    raise ValueError("this place is not in your list (any more)")


def state(conn: sqlite3.Connection) -> dict[str, Any]:
    """{sources, assets, accounts, questions}: everything the setup screen needs in one go."""
    counts = {r[0]: r[1] for r in conn.execute("SELECT source_id, COUNT(*) FROM accounts GROUP BY source_id")}
    sources = [dict(id=s["id"], name=s["name"], section=s["section"], source_type=s["source_type"], folder=s["folder"], connector=s["connector"],
                    active=s["active"], subfolders=s["options"].get("subfolders", True) is not False, accounts=counts.get(s["id"], 0))
               for s in db_accounts.list_sources(conn, active_only=False) if not s["options"].get("asset")]
    typed = db_assets.typed_balances(conn)
    accounts = [dict(id=a["id"], source_id=a["source_id"], name=a["name"], kind=a["kind"], balance=typed.get(a["id"], (None, None))[0],
                     balance_date=typed.get(a["id"], (None, None))[1])
                for a in db_accounts.list_accounts(conn) if a["kind"] in ("bank", "card", "depot", "crypto")]
    assets = [dict(a, id=a["account_id"]) for a in db_assets.list_assets(conn)]
    return dict(sources=sources, assets=assets, accounts=accounts, questions=db_questions.open_questions(conn))


def source_action(conn: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:
    """One change to the list of places: add / rename / folder / subfolders (on) / active (on) / delete. Returns {id} (add) or {removed} (delete)."""
    act = body.get("action")
    if act not in ACTIONS:
        raise ValueError("unknown change")
    if act == "add":
        section = str(body.get("section") or "")
        if section not in SECTIONS:
            raise ValueError("please pick bank, investment or crypto")
        api = body.get("source_type") == "api"
        name = _name(body.get("name"))
        with transaction(conn):
            if api:
                conn_id = " ".join(str(body.get("connector") or "").split())[:40]
                if not conn_id:
                    raise ValueError("please say which service to read from")
                sid = db_accounts.add_source(conn, name, section, "api", connector=conn_id, reader="auto")
            else:
                sid = db_accounts.add_source(conn, name, section, "folder", folder=_folder(body.get("folder")), reader="auto")
        return {"id": sid}
    s = _source(conn, body.get("id"))
    with transaction(conn):
        if act == "rename":
            conn.execute("UPDATE sources SET name=? WHERE id=?", (_name(body.get("name")), s["id"]))
        elif act == "folder":
            if s["source_type"] != "folder":
                raise ValueError("this place is not read from a folder")
            conn.execute("UPDATE sources SET folder=? WHERE id=?", (_folder(body.get("folder")), s["id"]))
        elif act == "subfolders":
            opts = dict(s["options"], subfolders=bool(body.get("on")))
            conn.execute("UPDATE sources SET options=? WHERE id=?", (json.dumps(opts), s["id"]))
        elif act == "active":
            db_accounts.set_source_active(conn, s["id"], bool(body.get("on")))
        else:      # delete: a place that already brought in data is only switched off, so nothing you have is lost
            if conn.execute("SELECT 1 FROM accounts WHERE source_id=? LIMIT 1", (s["id"],)).fetchone():
                db_accounts.set_source_active(conn, s["id"], False)
                return {"removed": False}
            conn.execute("DELETE FROM sources WHERE id=?", (s["id"],))
            return {"removed": True}
    return {"ok": True}


def asset_action(conn: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:
    """add (kind, fields) / update (id, fields) / delete (id) of a typed asset. Returns {id} for add."""
    act = body.get("action")
    raw = body.get("fields")
    fields: dict[str, Any] = raw if isinstance(raw, dict) else {}
    if act == "add":
        return {"id": db_assets.add_asset(conn, str(body.get("kind") or ""), fields)}
    aid = body.get("id")
    if not isinstance(aid, int):
        raise ValueError("this entry is not in your list (any more)")
    try:
        if act == "update":
            db_assets.update_asset(conn, aid, fields)
        elif act == "delete":
            db_assets.delete_asset(conn, aid)
        else:
            raise ValueError("unknown change")
    except KeyError:
        raise ValueError("this entry is not in your list (any more)") from None
    return {"ok": True}


def balance_action(conn: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:
    """The balance of an account whose files carry none: {account_id, value, date}."""
    aid = body.get("account_id")
    if not isinstance(aid, int) or conn.execute("SELECT 1 FROM accounts WHERE id=?", (aid,)).fetchone() is None:
        raise ValueError("this account is not in your list (any more)")
    db_assets.set_typed_balance(conn, aid, body.get("value"), str(body.get("date") or ""))      # type: ignore[arg-type]      # validated (German or English number) inside
    return {"ok": True}


def answer(conn: sqlite3.Connection, body: dict[str, Any]) -> dict[str, Any]:
    qid = body.get("id")
    return {"ok": isinstance(qid, int) and db_questions.answer(conn, qid, str(body.get("value") or ""))}


CLASS_ORDER = ("realEstate", "securities", "privateEquity", "cash", "crypto")      # the order of the asset classes everywhere on the dashboard
_BY_KIND = {"bank": "cash", "card": "cash", "depot": "securities", "crypto": "crypto", "property": "realEstate", "fund": "securities", "other": "privateEquity"}
_BY_SECTION = {"bank": "cash", "investment": "securities", "crypto": "crypto"}


def detected_classes(conn: sqlite3.Connection) -> list[str]:
    """The asset classes the setup implies (so the dashboard shows their boxes): every active place that was added and every typed asset, in dashboard order."""
    found: set[str] = set()
    live = set()
    for s in db_accounts.list_sources(conn):
        live.add(s["id"])
        if not s["options"].get("asset"):
            found.add(_BY_SECTION[s["section"]])
    for a in db_accounts.list_accounts(conn):
        if a["active"] and a["source_id"] in live and a["kind"] in _BY_KIND:
            found.add(_BY_KIND[a["kind"]])
    return [c for c in CLASS_ORDER if c in found]


def has_typed(conn: sqlite3.Connection) -> bool:
    """True when a house, loan, fund or other investment was typed in (the box for them is shown only then)."""
    return bool(db_assets.list_assets(conn))

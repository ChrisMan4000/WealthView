"""WealthView database, part 6 (v1.20): the plain questions the app asks when it cannot place a file, and the file formats it has learned.
A question is asked once per file layout (the column names). The answer is remembered in `formats`, so every file with the same columns is then read
the same way without asking again. ask() does not commit (the importer's transaction does); answer() commits by itself. Standard library only."""
from __future__ import annotations
import datetime as dt, json, sqlite3
from typing import Any

from .db_schema import transaction

FILE_KIND = "file_kind"
CHOICES: list[dict[str, str]] = [
    {"value": "bank", "label": "Bank account"},
    {"value": "card", "label": "Credit card"},
    {"value": "depot", "label": "Securities depot"},
    {"value": "trades", "label": "Securities trades"},
    {"value": "crypto", "label": "Crypto transactions"},
    {"value": "skip", "label": "Skip this file"},
]
WAITING = "waiting for your answer"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def format_for(conn: sqlite3.Connection, fingerprint: str) -> str | None:
    """The kind learned for a file layout ('bank' ... or 'skip'), None when this layout was never answered."""
    if not fingerprint:
        return None
    r = conn.execute("SELECT mapping FROM formats WHERE fingerprint=? AND confirmed=1", (fingerprint,)).fetchone()
    try:
        kind = json.loads(r[0]).get("kind") if r else None
    except (ValueError, AttributeError):
        return None
    return kind if isinstance(kind, str) else None


def ask(conn: sqlite3.Connection, source_id: int | None, file: str, path: str, fingerprint: str, guess: str = "") -> int:
    """Ask 'what is this file?' once per file layout; returns the question id (the open one when it already exists)."""
    for r in conn.execute("SELECT id, options FROM questions WHERE topic=? AND status='open'", (FILE_KIND,)):
        if _payload(r[1]).get("fingerprint") == fingerprint and fingerprint:
            return int(r[0])
    payload = {"choices": CHOICES, "fingerprint": fingerprint, "path": path, "guess": guess}
    cur = conn.execute("INSERT INTO questions(source_id,file,topic,options,status,created) VALUES(?,?,?,?, 'open', ?)",
                       (source_id, file, FILE_KIND, json.dumps(payload), _now()))
    return int(cur.lastrowid or 0)


def _payload(text: str | None) -> dict[str, Any]:
    try:
        val = json.loads(text) if text else {}
    except ValueError:
        return {}
    return val if isinstance(val, dict) else {}


def open_questions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The open questions: {id, source_id, file, topic, options [{value, label}], guess, created}, oldest first."""
    out = []
    for r in conn.execute("SELECT id,source_id,file,topic,options,created FROM questions WHERE status='open' ORDER BY id"):
        p = _payload(r[4])
        out.append({"id": r[0], "source_id": r[1], "file": r[2], "topic": r[3], "options": p.get("choices") or CHOICES, "guess": p.get("guess") or "",
                    "created": r[5]})
    return out


def answer(conn: sqlite3.Connection, question_id: int, value: str) -> bool:
    """Record the answer, learn the layout, and let the waiting files be read again at the next sync. False for an unknown question or choice."""
    row = conn.execute("SELECT options FROM questions WHERE id=? AND status='open'", (question_id,)).fetchone()
    if row is None or value not in {c["value"] for c in CHOICES}:
        return False
    fp = _payload(row[0]).get("fingerprint") or ""
    with transaction(conn):
        conn.execute("UPDATE questions SET answer=?, status='answered' WHERE id=?", (value, question_id))
        if fp:
            conn.execute("INSERT OR REPLACE INTO formats(fingerprint,kind,mapping,confirmed,created) VALUES(?,?,?,1,?)",
                         (fp, value, json.dumps({"kind": value}), _now()))
        for (sha,) in conn.execute("SELECT sha FROM files WHERE note=?", (WAITING,)).fetchall():
            conn.execute("DELETE FROM file_seen WHERE sha=?", (sha,))
            conn.execute("DELETE FROM files WHERE sha=?", (sha,))
    return True

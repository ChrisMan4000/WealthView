"""Automatic bank sync via FinTS/HBCI (v1.15, first part - not yet connected to the dashboard).

* The bank PIN lives in the Windows Credential Manager (target "WealthView-FinTS"), never in config.json or the database.
* The network part uses the optional package `python-fints` (pip install fints), imported only when a sync really runs.
* FinTS delivers no running balance, so imported rows carry balance NULL; `purge_covered()` removes them once the same booking
  arrives in a CSV export (same IBAN, date and amount), which keeps the CSV the master record.
Needs in config.json -> "fints": {"enabled": true, "blz": "43060967", "url": "<bank FinTS URL>", "login": "<Anmeldename>", "product_id": "<registered ID>"}.
"""
from __future__ import annotations
from typing import Any, Callable
import sqlite3, sys
from .db_import import booking_key

CRED_TARGET = "WealthView-FinTS"


def cred_write(secret: str, user: str = "pin", target: str = CRED_TARGET) -> bool:
    """store the PIN in the Windows Credential Manager; False off Windows"""
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class CRED(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    blob = secret.encode("utf-16-le")
    buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
    c = CRED(0, 1, target, None, wintypes.FILETIME(0, 0), len(blob), buf, 2, 0, None, None, user)
    return bool(ctypes.windll.advapi32.CredWriteW(ctypes.byref(c), 0))        # type: ignore[attr-defined]


def cred_read(target: str = CRED_TARGET) -> str | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    p = ctypes.c_void_p()
    if not ctypes.windll.advapi32.CredReadW(target, 1, 0, ctypes.byref(p)):        # type: ignore[attr-defined]
        return None

    class CRED(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_byte))]
    c = ctypes.cast(p, ctypes.POINTER(CRED)).contents
    try:
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
    finally:
        ctypes.windll.advapi32.CredFree(p)        # type: ignore[attr-defined]


def to_row(tx: Any, iban: str, account: str = "Giro") -> dict[str, Any]:
    """one python-fints/mt940 transaction -> the booking dict used by the database"""
    d = tx.data if hasattr(tx, "data") else tx
    amt = d["amount"]
    amount = float(getattr(amt, "amount", amt))
    return {"iban": iban, "account": account, "kind": "giro", "date": str(d["date"])[:10], "amount": amount,
            "counterparty": (d.get("applicant_name") or "")[:120], "cp_iban": d.get("applicant_iban") or "",
            "typ": d.get("posting_text") or "", "purpose": " ".join(str(d.get("purpose") or "").split()), "balance": None, "cat": None}


def import_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """insert bookings that are not known yet -> (rows seen, rows added). Known = same IBAN, date, amount and purpose start."""
    added = 0
    for r in rows:
        dup = conn.execute("SELECT 1 FROM bookings WHERE iban=? AND date=? AND ABS(amount-?)<0.005 AND substr(COALESCE(purpose,''),1,40)=substr(?,1,40) LIMIT 1",
                           (r["iban"], r["date"], r["amount"], r["purpose"])).fetchone()
        if dup:
            continue
        k = booking_key(r["iban"], r["date"], r["amount"], None, r["purpose"], r["counterparty"])
        cur = conn.execute("INSERT OR IGNORE INTO bookings(bkey,account,kind,iban,date,counterparty,cp_iban,type,purpose,amount,balance,category,file_id,fkey,ord) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,NULL,?,NULL,0,0)",
                           (k, r["account"], r["kind"], r["iban"], r["date"], r["counterparty"], r["cp_iban"], r["typ"], r["purpose"], r["amount"], r["cat"]))
        added += cur.rowcount
    return len(rows), added


def purge_covered(conn: sqlite3.Connection) -> int:
    """delete FinTS rows (no balance, no file) that a CSV row (has a balance) now covers"""
    cur = conn.execute("DELETE FROM bookings WHERE file_id IS NULL AND balance IS NULL AND EXISTS ("
                       "SELECT 1 FROM bookings c WHERE c.balance IS NOT NULL AND c.iban=bookings.iban AND c.date=bookings.date AND ABS(c.amount-bookings.amount)<0.005)")
    return cur.rowcount


def fetch(cfg: dict[str, Any], since: str, ask_tan: Callable[[str], None] | None = None) -> list[dict[str, Any]]:
    """log in with the stored PIN and read the bookings since `since` (YYYY-MM-DD). Raises RuntimeError with a plain message on any problem."""
    if not cfg.get("enabled"):
        raise RuntimeError("FinTS sync is switched off in config.json (fints.enabled)")
    for k in ("blz", "url", "login", "product_id"):
        if not cfg.get(k):
            raise RuntimeError(f"config.json fints.{k} is missing")
    pin = cred_read()
    if not pin:
        raise RuntimeError("No bank PIN stored in the Windows Credential Manager yet")
    try:
        from fints.client import FinTS3PinTanClient, NeedTANResponse        # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError("The package python-fints is missing: run  pip install fints  once") from e
    import datetime as dt, time
    c = FinTS3PinTanClient(cfg["blz"], cfg["login"], pin, cfg["url"], product_id=cfg["product_id"])
    out: list[dict[str, Any]] = []
    with c:
        if c.init_tan_response:
            _wait_decoupled(c, c.init_tan_response, ask_tan, time)
        for acc in c.get_sepa_accounts():
            res = c.get_transactions(acc, dt.date.fromisoformat(since), dt.date.today())
            while isinstance(res, NeedTANResponse):
                res = _wait_decoupled(c, res, ask_tan, time)
            out += [to_row(t, acc.iban) for t in res]
    return out


def _wait_decoupled(client: Any, resp: Any, ask_tan: Callable[[str], None] | None, time_mod: Any) -> Any:
    """decoupled TAN (approve in the GLS app): poll until the bank confirms, at most 2 minutes"""
    if ask_tan:
        ask_tan(str(getattr(resp, "challenge", "Approve the login in your bank app")))
    for _ in range(40):
        time_mod.sleep(3)
        r = client.send_tan(resp, "")
        if r is not None and not hasattr(r, "challenge"):
            return r
    raise RuntimeError("The bank app did not confirm within 2 minutes")

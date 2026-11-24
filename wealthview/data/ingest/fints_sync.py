"""Automatic bank sync via FinTS/HBCI (v1.24: connected to the refresh).

* Login data (BLZ, FinTS address, login name, product ID, PIN) is saved by the setup screen in the Windows Credential Manager (keystore),
  never in config.json or the database. Only READ calls are made at the bank (accounts, balance, transactions, securities) - never a payment: the client is wrapped in `_ReadOnly`.
* The network part uses the optional package `python-fints` (pip install fints), imported only when a sync really runs.
* FinTS delivers no running balance per booking: it is computed backwards from the balance the bank reports now, so the rows fit the CSV balances.
  A CSV export that arrives later replaces the matching FinTS rows (`purge_covered`), one row for one row.
* Safety: a wrong PIN blocks further attempts until the PIN is saved again (the bank locks the account after a few); an attempt is made at most
  every `fints.min_hours` (default 12) hours, because every attempt sends a push to the phone.
"""
from __future__ import annotations
from typing import Any, Callable
import datetime as dt, re, sqlite3
from ...common.types.accounts import SourceRow
from ...common.types.status import BankSyncReport
from . import db_accounts
from .credstore import CRED_TARGET, cred_read, cred_write      # noqa: F401  (stay importable from here)
from .db_import import booking_key


def to_row(tx: Any, iban: str, account: str = "Giro") -> dict[str, Any]:
    """one python-fints/mt940 transaction -> the booking dict used by the database"""
    d = tx.data if hasattr(tx, "data") else tx
    amt = d["amount"]
    amount = float(getattr(amt, "amount", amt))
    return {"iban": iban, "account": account, "kind": "giro", "date": str(d["date"])[:10], "amount": amount,
            "counterparty": (d.get("applicant_name") or "")[:120], "cp_iban": d.get("applicant_iban") or "",
            "typ": d.get("posting_text") or "", "purpose": " ".join(str(d.get("purpose") or "").split()), "balance": None, "cat": None}


class FintsError(RuntimeError):
    """a bank-sync problem with a plain message; `code` is wrong_pin, not_approved, unreachable, product_rejected, setup or bank"""
    def __init__(self, msg: str, code: str = "bank") -> None:
        super().__init__(msg)
        self.code = code


# The ONLY things WealthView may do at the bank. Everything else (payments, direct debits, standing orders, ...) is refused by `_ReadOnly`
# before it can reach the library, and a test (`test_only_allowed_bank_calls_in_the_source`) checks the code for any other call.
READ_ONLY = frozenset({
    "get_sepa_accounts", "get_balance", "get_transactions", "get_holdings", "get_information",
    "fetch_tan_mechanisms", "get_tan_mechanisms", "get_current_tan_mechanism", "set_tan_mechanism", "is_tan_media_required", "get_tan_media", "set_tan_medium",
    "send_tan",        # only to confirm the login/read request we just made (decoupled push), never to start anything
    "init_tan_response", "selected_tan_medium"})
SETTABLE = frozenset({"selected_tan_medium"})


class _ReadOnly:
    """wraps the python-fints client: any call or setting outside READ_ONLY raises FintsError instead of reaching the bank"""
    def __init__(self, client: Any) -> None:
        object.__setattr__(self, "_c", client)

    def __getattr__(self, name: str) -> Any:
        if name not in READ_ONLY:
            raise FintsError(f"blocked: '{name}' is not a read-only bank call - WealthView never sends payments", "blocked")
        return getattr(self._c, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name not in SETTABLE:
            raise FintsError(f"blocked: '{name}' may not be changed", "blocked")
        setattr(self._c, name, value)

    def __enter__(self) -> "_ReadOnly":
        self._c.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._c.__exit__(*exc)


DAY_WINDOW = 5      # the bank dates a booking up to a few days apart from the CSV export (booking day vs value day)


def _kind_for(name: str) -> str:
    n = name.lower()
    return "card" if ("kredit" in n or "card" in n) else "tages" if "tagesgeld" in n else "shares" if ("anteil" in n or "share" in n) else "giro"


def labels(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """IBAN -> (account name, kind) as the CSV rows and the accounts list already call it, so bank rows land in the same account"""
    out: dict[str, tuple[str, str]] = {}
    for iban, name in conn.execute("SELECT ident, name FROM accounts WHERE ident IS NOT NULL AND length(ident)>=15"):
        out[iban] = (name, _kind_for(name))
    for iban, acc, kind in conn.execute("SELECT iban, account, kind FROM bookings WHERE file_id IS NOT NULL AND iban IS NOT NULL ORDER BY date, id"):
        out[iban] = (acc, kind)
    return out


def relabel(conn: sqlite3.Connection) -> int:
    """give bank rows the account name and kind of their IBAN (repairs rows that were all called 'Giro')"""
    n = 0
    for iban, (acc, kind) in labels(conn).items():
        n += conn.execute("UPDATE bookings SET account=?, kind=? WHERE file_id IS NULL AND iban=? AND (account IS NOT ? OR kind IS NOT ?)", (acc, kind, iban, acc, kind)).rowcount
    return n


def _same(r: dict[str, Any], ex: Any) -> bool:
    """an existing row (id, balance, purpose, date) is the same booking as the fetched row r: with both balances known the balance after the booking
    decides (the date may differ a few days); otherwise the same day"""
    if ex[1] is not None and r["balance"] is not None:
        return abs(ex[1] - r["balance"]) < 0.005
    return ex[3] == r["date"]


def import_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]], dry_run: bool = False) -> tuple[int, int]:
    """insert bookings that are not known yet -> (rows seen, rows added). Known = same IBAN and amount within a few days, with the same balance after
    the booking; every existing row covers ONE fetched row, so two equal bookings on one day both stay."""
    added = 0
    used: set[int] = set()
    for i, r in enumerate(rows):
        cands = conn.execute("SELECT id,balance,purpose,date FROM bookings WHERE iban=? AND ABS(amount-?)<0.005 AND date BETWEEN date(?,?) AND date(?,?)",
                             (r["iban"], r["amount"], r["date"], f"-{DAY_WINDOW} day", r["date"], f"+{DAY_WINDOW} day")).fetchall()
        hit = next((c for c in cands if c[0] not in used and _same(r, c)), None)
        if hit:
            used.add(hit[0])
            continue
        if dry_run:
            added += 1
            continue
        k = booking_key(r["iban"], r["date"], r["amount"], r["balance"], r["purpose"], r["counterparty"])
        cur = conn.execute("INSERT OR IGNORE INTO bookings(bkey,account,kind,iban,date,counterparty,cp_iban,type,purpose,amount,balance,category,file_id,fkey,ord) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,0,?)",
                           (k, r["account"], r["kind"], r["iban"], r["date"], r["counterparty"], r["cp_iban"], r["typ"], r["purpose"], r["amount"], r["balance"], r["cat"], i))
        if cur.rowcount and cur.lastrowid:
            used.add(cur.lastrowid)
        added += cur.rowcount
    return len(rows), added


def purge_covered(conn: sqlite3.Connection) -> int:
    """delete bank rows (no file) that a CSV row (has a file) now covers - same IBAN and amount within a few days and the same balance; one CSV row removes one bank row"""
    gone = 0
    taken: set[int] = set()
    for fid, iban, date, amount, bal in conn.execute("SELECT id,iban,date,amount,balance FROM bookings WHERE file_id IS NULL").fetchall():
        for cid, cbal, cdate in conn.execute("SELECT id,balance,date FROM bookings WHERE file_id IS NOT NULL AND iban=? AND ABS(amount-?)<0.005 AND date BETWEEN date(?,?) AND date(?,?)",
                                             (iban, amount, date, f"-{DAY_WINDOW} day", date, f"+{DAY_WINDOW} day")).fetchall():
            if cid not in taken and cbal is not None and ((bal is not None and abs(cbal - bal) < 0.005) or (bal is None and cdate == date)):
                taken.add(cid)
                conn.execute("DELETE FROM bookings WHERE id=?", (fid,))
                gone += 1
                break
    return gone


def _num(x: Any) -> float | None:
    try:
        return None if x is None else float(getattr(x, "amount", x))
    except (TypeError, ValueError):
        return None


def _holdings(c: Any, need_tan: Any, wait: Callable[[Any], Any], number: str | None = None, blz: str = "") -> dict[str, Any]:
    """try the securities accounts of the login: {positions: [{isin, name, pieces, price, value, currency, date}], notes: [why not]} - read only"""
    out: dict[str, Any] = dict(positions=[], notes=[])
    try:
        from fints.client import FinTSOperations        # type: ignore[import-not-found]
        from fints.models import SEPAAccount        # type: ignore[import-not-found]
        info = c.get_information()
        bic = next((a.bic for a in c.get_sepa_accounts() if getattr(a, "bic", None)), "GENODEM1GLS")
        depots = [a for a in info.get("accounts", []) if (a.get("supported_operations") or {}).get(FinTSOperations.GET_HOLDINGS)]
        if not depots:
            asks = (info.get("bank", {}).get("supported_operations") or {}).get(FinTSOperations.GET_HOLDINGS)
            out["notes"].append("the bank lists no securities account for this login" + (f"; it says it {'supports' if asks else 'does not support'} securities queries" if asks is not None else ""))
            if number:      # a bank may answer for a depot it does not list: ask once for the depot number known from the depot files (still read only)
                import types
                depots = [dict(iban=None, account_number=number, subaccount_number="", bank_identifier=types.SimpleNamespace(bank_code=blz))]
                out["notes"].append("asked directly for the depot number from your depot files")
        for a in depots:
            sa = SEPAAccount(a.get("iban"), bic, a.get("account_number"), a.get("subaccount_number") or "", a["bank_identifier"].bank_code)
            res = c.get_holdings(sa)
            while isinstance(res, need_tan):
                res = wait(res)
            if not res:
                out["notes"].append("the securities account answered with no positions")
            out["positions"] += [dict(isin=h.ISIN, name=h.name, pieces=_num(h.pieces), price=_num(h.market_value), value=_num(h.total_value),
                                      currency=h.value_symbol, date=str(h.valuation_date or "")[:10]) for h in (res or [])]
    except Exception as e:      # broad on purpose: a bank without this function must never spoil the booking sync
        out["notes"].append("reading securities failed (" + type(e).__name__ + (": " + str(e)[:100] if str(e) else "") + ")")
    return out


def fetch_all(keys: dict[str, Any], since: str, ask_tan: Callable[[str], None] | None = None, depot: bool = False, depot_number: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """log in ONCE (one confirmation in the bank app) and read the bookings since `since` with the balance, and optionally the securities.
    Raises FintsError (a RuntimeError) with a plain message."""
    for k in ("blz", "url", "login", "product_id", "pin"):
        if not keys.get(k):
            raise FintsError(f"the bank connection lacks '{k}' - open Setup and fill it in", "setup")
    try:
        from fints.client import FinTS3PinTanClient, NeedTANResponse        # type: ignore[import-not-found]
    except ImportError as e:
        raise FintsError("The package python-fints is missing: run  pip install fints  once", "setup") from e
    import time
    out: list[dict[str, Any]] = []
    held: dict[str, Any] | None = None
    try:
        c = _ReadOnly(FinTS3PinTanClient(keys["blz"], keys["login"], keys["pin"], keys["url"], product_id=keys["product_id"]))
        _choose_tan(c)
        wait = lambda resp: _wait_decoupled(c, resp, ask_tan, time)
        with c:
            if c.init_tan_response:
                wait(c.init_tan_response)
            for acc in c.get_sepa_accounts():
                res = c.get_transactions(acc, dt.date.fromisoformat(since), dt.date.today())
                while isinstance(res, NeedTANResponse):
                    res = wait(res)
                bal = c.get_balance(acc)
                while isinstance(bal, NeedTANResponse):
                    bal = wait(bal)
                rows = [to_row(t, acc.iban) for t in res]
                out += _with_balances(rows, float(getattr(getattr(bal, "amount", None), "amount", getattr(bal, "amount", 0)))) if bal is not None else rows
            if depot:
                held = _holdings(c, NeedTANResponse, wait, depot_number, str(keys["blz"]))
    except FintsError:
        raise
    except Exception as e:      # broad on purpose: the library raises many types; the message must stay plain and never contain the PIN
        name = type(e).__name__
        if "PIN" in name.upper():
            raise FintsError("The bank refused the login (wrong PIN or login name). Sync is paused: save the PIN again in Setup.", "wrong_pin") from None
        if isinstance(e, (OSError, TimeoutError)) or "Connection" in name:
            raise FintsError("The bank could not be reached right now.", "unreachable") from None
        if "product" in str(e).lower():
            raise FintsError("The bank does not accept the FinTS product ID.", "product_rejected") from None
        raise FintsError("The bank answered with an error (" + name + ").", "bank") from None
    return out, held


def fetch(keys: dict[str, Any], since: str, ask_tan: Callable[[str], None] | None = None) -> list[dict[str, Any]]:
    """the bookings since `since` (YYYY-MM-DD) with balances - see fetch_all"""
    return fetch_all(keys, since, ask_tan)[0]


def _choose_tan(c: Any) -> None:
    """what python-fints' interactive bootstrap asks, decided without a question: the push (decoupled) method when the bank offers several,
    and the only / first TAN medium"""
    if not c.get_current_tan_mechanism():
        c.fetch_tan_mechanisms()
        mechs = list(c.get_tan_mechanisms().items())
        if len(mechs) > 1:
            pick = next((m for m in mechs if any(w in str(getattr(m[1], "name", "")).lower() for w in ("securego", "push", "decoupled"))), mechs[0])
            c.set_tan_mechanism(pick[0])
    if c.selected_tan_medium is None and c.is_tan_media_required():
        media = c.get_tan_media()[1]
        c.selected_tan_medium = "" if not media else None
        if media:
            c.set_tan_medium(media[0])


def _with_balances(rows: list[dict[str, Any]], current: float) -> list[dict[str, Any]]:
    """rows oldest first as the bank lists them; the last row's balance is the account balance now, each earlier one follows backwards"""
    bal = current
    for r in reversed(rows):
        r["balance"] = round(bal, 2)
        bal -= r["amount"]
    return rows


def _wait_decoupled(client: Any, resp: Any, ask_tan: Callable[[str], None] | None, time_mod: Any, polls: int = 40) -> Any:
    """decoupled TAN (approve in the GLS app): poll until the bank confirms, at most 2 minutes"""
    if ask_tan:
        ask_tan(str(getattr(resp, "challenge", "Approve the login in your bank app")))
    for _ in range(polls):
        time_mod.sleep(3)
        r = client.send_tan(resp, "")
        if r is not None and not hasattr(r, "challenge"):
            return r
    raise FintsError("The bank app did not confirm within 2 minutes - nothing was imported, the next refresh tries again.", "not_approved")


def _meta(conn: sqlite3.Connection, k: str) -> Any:
    return (conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone() or [None])[0]


def _setmeta(conn: sqlite3.Connection, k: str, v: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, v))


def _tried_recently(conn: sqlite3.Connection, place_id: int, now: dt.datetime, min_hours: float, force: bool) -> bool:
    """every attempt sends a push to the phone, so a place is asked at most every min_hours hours (unless forced)"""
    last = _meta(conn, f"fints_try_{place_id}")
    return bool(last and not force and (now - dt.datetime.fromisoformat(last)).total_seconds() < min_hours * 3600)


def _since_date(newest: str | None, now: dt.datetime) -> str:
    """read from a week before the newest known booking, or a year back on an empty database"""
    return (dt.date.fromisoformat(newest) - dt.timedelta(days=7)).isoformat() if newest else (now.date() - dt.timedelta(days=365)).isoformat()


def _relabel_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    lab = labels(conn)
    for r in rows:
        r["account"], r["kind"] = lab.get(r["iban"], (r["account"], _kind_for(r["account"])))


def _gap_warning(name: str, rows: list[dict[str, Any]], newest: str | None) -> str | None:
    """a warning when the bank's oldest returned booking is newer than what we already hold (a gap in between)"""
    if rows and newest and min(r["date"] for r in rows) > newest:
        return f"{name}: the bank returned bookings only from {min(r['date'] for r in rows)} - bookings after {newest} may be missing"
    return None


def _depot_number(conn: sqlite3.Connection) -> str | None:
    """the depot number is part of the bank's export file name (Depotbestand_<number>_<date>.csv)"""
    last = conn.execute("SELECT name FROM files WHERE name LIKE 'Depotbestand\\_%' ESCAPE '\\' ORDER BY id DESC LIMIT 1").fetchone()
    m = re.match(r"Depotbestand_(\d{6,})_", last[0]) if last else None
    return m.group(1) if m else None


def merge_holdings(conn: sqlite3.Connection, source_id: int, held: dict[str, Any] | None, now: dt.datetime, dry_run: bool = False) -> tuple[str | None, str | None]:
    """Today's depot from the bank's securities answer -> (note, warning). The bank sends only pieces, price and value (no ISIN, no name), so every bank
    row is matched to a position we already know BY ITS PIECES (the newest depot snapshot: a depot file or the last bank snapshot) and keeps that
    position's WKN, name and cost. A row with no price is an unpriced / discontinued fund: value 0. Known positions the bank no longer lists were sold
    and drop out. If any bank row matches nothing (pieces changed: a purchase or sale), NOTHING is written and a warning asks for a fresh depot file."""
    bank = [p for p in ((held or {}).get("positions") or []) if p.get("pieces")]
    if not bank:
        return None, None
    prev = conn.execute("SELECT p.wkn,p.name,p.qty,p.price,p.value,p.gain FROM depot_positions p JOIN accounts a ON a.id=p.account_id WHERE a.kind='depot' "
                        "AND p.asof=(SELECT MAX(q.asof) FROM depot_positions q JOIN accounts b ON b.id=q.account_id WHERE b.kind='depot')").fetchall()
    free, pairs, lost = list(prev), [], 0
    for b in sorted(bank, key=lambda x: -(x.get("value") or 0)):
        cands = [r for r in free if abs((r[2] or 0) - b["pieces"]) < 1e-6]
        if len(cands) > 1 and b.get("price") is not None:       # same pieces twice: the closer old price decides
            cands.sort(key=lambda r: abs((r[3] or 0) - b["price"]))
            cands = cands[:1] if abs((cands[0][3] or 0) - b["price"]) < abs((cands[1][3] or 0) - b["price"]) else []
        if len(cands) == 1:
            free.remove(cands[0])
            pairs.append((cands[0], b))
        else:
            lost += 1
    if lost or not pairs:
        return None, (f"depot from the bank NOT used: {lost or len(bank)} of {len(bank)} bank positions match no known position by pieces "
                      "(bought or sold something?) - export a fresh 'Depotbestand' from GLS into the DATA folder")
    rows = []
    for r, b in pairs:
        pcs, price = b["pieces"], b.get("price")
        val = 0.0 if price is None else (b["value"] if b.get("value") and abs(b["value"] - pcs * price) <= 0.01 * pcs * price else round(pcs * price, 2))
        cost = (r[4] - r[5]) if r[4] is not None and r[5] is not None else None
        gain = round(val - cost, 2) if cost is not None else None
        rows.append((r[0], r[1], pcs, price, val, gain, round(gain / cost * 100, 2) if gain is not None and cost else None))
    note = f" · depot from the bank: {len(rows)} positions" + (f", {len(free)} sold ({', '.join((r[1] or r[0]) for r in free)})" if free else "")
    if not dry_run:
        acc = db_accounts.account_for(conn, source_id, _depot_number(conn) or "depot", "Depot", "depot")
        conn.execute("DELETE FROM depot_positions WHERE account_id=?", (acc,))       # the bank account holds only its newest snapshot
        conn.executemany("INSERT OR REPLACE INTO depot_positions(account_id,asof,wkn,name,qty,price,value,gain,gain_pct,file_id) VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                         [(acc, now.date().isoformat(), *x) for x in rows])
    return note, None


def _sync_place(conn: sqlite3.Connection, s: SourceRow, rep: BankSyncReport, load_keys: Callable[[int], dict[str, Any]], ask_tan: Callable[[str], None] | None,
                dry_run: bool, force: bool, now: dt.datetime, min_hours: float, holdings: bool = False) -> None:
    """one bank place: throttle / block checks, fetch, relabel, import; its outcome is merged into rep"""
    blocked = _meta(conn, f"fints_blocked_{s['id']}")
    if blocked:
        rep.update(status="warn", message=f"{s['name']}: " + str(blocked))
        return
    if _tried_recently(conn, s["id"], now, min_hours, force):
        rep.update(status=rep["status"] if rep["status"] != "off" else "ok", message=rep["message"] or "bank checked recently")
        return
    keys = load_keys(s["id"])
    newest = conn.execute("SELECT MAX(date) FROM bookings").fetchone()[0]
    since = _since_date(newest, now)
    if not dry_run:
        _setmeta(conn, f"fints_try_{s['id']}", now.isoformat(timespec="seconds"))
    held = None
    try:
        if holdings:        # ONE login for bookings and securities
            rows, held = fetch_all(keys, since, ask_tan, depot=True, depot_number=_depot_number(conn))
        else:
            rows = fetch(keys, since, ask_tan)
    except FintsError as e:
        if e.code == "wrong_pin" and not dry_run:
            _setmeta(conn, f"fints_blocked_{s['id']}", str(e))
        rep.update(status="warn", message=f"{s['name']}: {e}")
        rep["warnings"].append(str(e))
        return
    _relabel_rows(conn, rows)
    seen, added = import_rows(conn, rows, dry_run)
    rep["rows"] += seen
    rep["added"] += added
    gap = _gap_warning(s["name"], rows, newest)
    if gap:
        rep["warnings"].append(gap)
    note = None
    if held is not None:
        note, warn = merge_holdings(conn, s["id"], held, now, dry_run)
        if warn:
            rep["warnings"].append(warn)
    rep.update(status="warn" if rep["warnings"] else "ok", message=f"{s['name']}: {added} new bookings from the bank" + (note or "") + (" (test run, nothing saved)" if dry_run else ""))


def sync_bank(conn: sqlite3.Connection, places: list[SourceRow], load_keys: Callable[[int], dict[str, Any]], ask_tan: Callable[[str], None] | None = None,
              dry_run: bool = False, force: bool = False, now: dt.datetime | None = None, min_hours: float = 12, holdings: bool = False) -> BankSyncReport:
    """read every FinTS bank place (sources of connector fints) with the keys `load_keys(id)` -> {status: off|ok|warn, added, rows, warnings, message}.
    Never raises for bank problems."""
    rep = BankSyncReport(status="off", added=0, rows=0, warnings=[], message="")
    if not places:
        return rep
    now = now or dt.datetime.now()
    for s in places:
        _sync_place(conn, s, rep, load_keys, ask_tan, dry_run, force, now, min_hours, holdings)
    if not dry_run:
        purge_covered(conn)
        relabel(conn)
        conn.commit()
    return rep

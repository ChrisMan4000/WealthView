"""WealthView v1.22: Coinbase balances and transactions read in Python (it replaces coinbase_fetch.mjs, so Coinbase no longer needs Node.js).
Read-only: only GET requests are made, each signed with a short-lived token (CDP API key, Ed25519 / EdDSA JWT). The key never appears in an error
text, a log or the result. The answer has the shape coinbase_fetch.mjs printed: {ok, source, trades_status, txs, total_eur, holdings}.
Standard library only (the signature comes from ed25519.py)."""
from __future__ import annotations
import base64, binascii, json, os, time, urllib.error, urllib.request
from typing import Any, Callable

from ...common import netlog, safenet
from . import ed25519

HOST = "api.coinbase.com"
FIAT = {"EUR", "USD", "GBP", "CHF"}
TIMEOUT = 20
Get = Callable[[str], Any]


class CoinbaseError(RuntimeError):
    """A plain sentence about why Coinbase could not be read (never contains the key)."""


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def seed_of(secret: str) -> bytes:
    """The 32-byte Ed25519 seed inside the API secret Coinbase shows (base64 of 32 or 64 bytes)."""
    s = "".join(str(secret or "").replace("\\n", "\n").split())
    if "BEGIN" in s and "PRIVATE" in s:
        raise CoinbaseError("this API key uses the ECDSA signature. Please create a new Coinbase API key and choose the signature Ed25519")
    try:
        raw = base64.b64decode(s + "=" * (-len(s) % 4), validate=True)
    except (binascii.Error, ValueError):
        raise CoinbaseError("the API secret does not look like a Coinbase Ed25519 secret (it should be one line of letters and digits)") from None
    if len(raw) not in (32, 64):
        raise CoinbaseError("the API secret has an unexpected length. Please create a Coinbase API key with the signature Ed25519")
    return raw[:32]


def jwt(name: str, seed: bytes, method: str, path: str, now: float | None = None, nonce: str | None = None) -> str:
    t = int(now if now is not None else time.time())
    header = {"alg": "EdDSA", "typ": "JWT", "kid": name, "nonce": nonce or os.urandom(16).hex()}
    payload = {"sub": name, "iss": "cdp", "nbf": t, "exp": t + 120, "uri": f"{method} {HOST}{path}"}
    body = _b64u(json.dumps(header, separators=(",", ":")).encode()) + "." + _b64u(json.dumps(payload, separators=(",", ":")).encode())
    return body + "." + _b64u(ed25519.sign(seed, body.encode()))


def _getter(name: str, seed: bytes) -> Get:
    def get(path_query: str) -> Any:
        path = path_query.split("?")[0]
        req = urllib.request.Request(f"https://{HOST}{path_query}", headers={
            "Authorization": "Bearer " + jwt(name, seed, "GET", path), "CB-VERSION": "2024-10-01", "Accept": "application/json",
            "User-Agent": safenet.DEFAULT_HEADERS.get("User-Agent", "WealthView")})
        try:
            with safenet.urlopen(req, TIMEOUT) as r:
                return json.loads(r.read(safenet.MAX_BYTES).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = " ".join(e.read(300).decode("utf-8", "replace").split())
            except OSError:
                pass
            raise CoinbaseError(f"HTTP {e.code} {path}: {body[:160]}") from None
        except (OSError, ValueError) as e:
            raise CoinbaseError(f"no answer from Coinbase ({type(e).__name__})") from None
    return get


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _spot(cur: str, public_get: Callable[[str], Any]) -> float | None:
    if cur == "EUR":
        return 1.0
    try:
        return float(public_get(f"https://{HOST}/v2/prices/{cur}-EUR/spot")["data"]["amount"])
    except (*safenet.NET_ERRORS, KeyError, TypeError):
        return None


def _via_v2(get: Get) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    nxt: str | None = "/v2/accounts?limit=100"
    for _ in range(10):
        if not nxt:
            break
        j = get(nxt)
        rows += j.get("data") or []
        nxt = (j.get("pagination") or {}).get("next_uri")
    every = [{"id": a["id"], "currency": a["balance"]["currency"]} for a in rows]
    hold = []
    for a in rows:
        bal = _num(a["balance"]["amount"])
        if not bal > 0:
            continue
        cur = a["balance"]["currency"]
        nb = a.get("native_balance") or {}
        hold.append({"id": a["id"], "currency": cur, "name": (a.get("currency") or {}).get("name") or cur if isinstance(a.get("currency"), dict) else cur,
                     "amount": bal, "eur": _num(nb.get("amount")) if nb.get("currency") == "EUR" else None})
    return hold, every


def _via_v3(get: Get) -> list[dict[str, Any]]:
    hold: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(10):
        j = get("/api/v3/brokerage/accounts?limit=250" + ("&cursor=" + cursor if cursor else ""))
        for a in j.get("accounts") or []:
            bal = _num((a.get("available_balance") or {}).get("value")) + _num((a.get("hold") or {}).get("value"))
            if bal > 0:
                hold.append({"currency": a["currency"], "name": a.get("name") or a["currency"], "amount": bal, "eur": None})
        if not j.get("has_next"):
            break
        cursor = j.get("cursor") or ""
    return hold


def _transactions(get: Get, account_id: str) -> list[dict[str, Any]]:
    """Buys, sells and transfers of one account, flattened (lots.py maps them to trades)."""
    rows: list[dict[str, Any]] = []
    nxt: str | None = f"/v2/accounts/{account_id}/transactions?limit=100"
    for _ in range(20):
        if not nxt:
            break
        j = get(nxt)
        for t in j.get("data") or []:
            na = t.get("native_amount")
            rows.append({"type": t.get("type"), "date": str(t.get("created_at") or "")[:10], "qty": _num((t.get("amount") or {}).get("amount")),
                         "native": _num(na.get("amount")) if na else None, "native_cur": na.get("currency") if na else None})
        nxt = (j.get("pagination") or {}).get("next_uri")
    return rows


def fetch(name: str, secret: str, get: Get | None = None, public_get: Callable[[str], Any] | None = None, transactions: bool = True) -> dict[str, Any]:
    """Balances (EUR value per coin) and, when the key may read them, the transactions per coin. CoinbaseError with a plain sentence on failure."""
    if not name or not secret:
        raise CoinbaseError("the API key name or the API secret is missing")
    get = get or _getter(str(name).strip(), seed_of(secret))
    public_get = public_get or (lambda url: safenet.fetch_json(url, TIMEOUT))
    netlog.log(HOST, "Coinbase")
    source, every = "v2", []
    try:
        hold, every = _via_v2(get)
    except (CoinbaseError, KeyError, TypeError, AttributeError) as e1:
        source = "v3"
        try:
            hold = _via_v3(get)
        except (CoinbaseError, KeyError, TypeError, AttributeError) as e2:
            raise CoinbaseError(f"{e1} | {e2}"[:300]) from None
    for h in hold:
        if h["eur"] is None:
            p = _spot(h["currency"], public_get)
            h["eur"], h["price"] = (None if p is None else h["amount"] * p), p
        else:
            h["price"] = h["eur"] / h["amount"] if h["amount"] else None
    hold.sort(key=lambda h: -(h["eur"] or 0))
    txs: dict[str, list[dict[str, Any]]] = {}
    trades_status = "none"
    if source == "v2" and transactions:      # 'no_permission' when the key may not read transactions; 'none' when only the v3 fallback worked
        trades_status = "ok"
        held = {h["currency"] for h in hold}
        for a in every:
            if a["currency"] in held and a["currency"] not in FIAT:
                try:
                    txs.setdefault(a["currency"], []).extend(_transactions(get, a["id"]))
                except CoinbaseError as e:
                    trades_status = "no_permission" if ("HTTP 401" in str(e) or "HTTP 403" in str(e)) else "error"
                    txs = {}
                    break
    total = sum(h["eur"] or 0 for h in hold)
    return {"ok": True, "source": source, "trades_status": trades_status, "txs": txs, "total_eur": round(total, 2),
            "holdings": [{k: (None if k == "eur" and v is None else round(v, 2) if k == "eur" else v) for k, v in h.items() if k != "id"} for h in hold]}

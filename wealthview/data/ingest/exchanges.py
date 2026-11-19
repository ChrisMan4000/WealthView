"""WealthView v1.21: balances of crypto exchanges read through their API with a read-only key (Binance, Kraken; Coinbase keeps its own reader,
coinbase_fetch.mjs, and only gets its keys from here). Only signed GET / balance calls are made: nothing can be traded or moved.
The keys come from keystore (Windows Credential Manager) and never appear in an error text, a log or the result. Standard library only."""
from __future__ import annotations
import base64, hashlib, hmac, json, sqlite3, time, urllib.error, urllib.parse, urllib.request
from typing import Any, Callable

from ...common import netlog, safenet
from ...common.parsing import round2
from ...common.runcontext import RunContext
from ...common.timeutil import now
from ...common.types.depot import CryptoBlock, Holding
from . import coinbase_api, connectors, db_accounts, keystore

FIAT_EUR = {"EUR": 1.0}
TIMEOUT = 20
Http = Callable[[urllib.request.Request], Any]


class ExchangeError(RuntimeError):
    """A plain sentence about why an exchange could not be read (never contains a key)."""


def _http(req: urllib.request.Request) -> Any:
    try:
        with safenet.urlopen(req, TIMEOUT) as r:
            return json.loads(r.read(safenet.MAX_BYTES).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(400).decode("utf-8", "replace")
        except OSError:
            pass
        raise ExchangeError(f"the exchange answered {e.code}: {' '.join(body.split())[:160]}") from None
    except (OSError, ValueError) as e:
        raise ExchangeError(f"no answer from the exchange ({type(e).__name__})") from None


def binance_asset(code: str) -> str:
    """Binance shows coins in flexible Earn with the prefix LD (LDBTC = BTC)."""
    return code[2:] if code.startswith("LD") and len(code) >= 5 else code


def binance_sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def kraken_sign(secret: str, path: str, nonce: str, post: str) -> str:
    """Kraken's API-Sign header. ValueError when the private key is not base64."""
    mac = hmac.new(base64.b64decode(secret), path.encode() + hashlib.sha256((nonce + post).encode()).digest(), hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def binance_balances(keys: dict[str, str], http: Http = _http, now_ms: Callable[[], int] = lambda: int(time.time() * 1000)) -> dict[str, float]:
    """coin -> amount (free + locked) of the Binance spot wallet."""
    key, secret = keys.get("api_key", ""), keys.get("api_secret", "")
    if not key or not secret:
        raise ExchangeError("the API key or the secret key is missing")
    query = urllib.parse.urlencode({"omitZeroBalances": "true", "recvWindow": 10000, "timestamp": now_ms()})
    sig = binance_sign(secret, query)
    netlog.log("api.binance.com", "Binance")
    res = http(urllib.request.Request(f"https://api.binance.com/api/v3/account?{query}&signature={sig}", headers={"X-MBX-APIKEY": key}))
    if not isinstance(res, dict) or not isinstance(res.get("balances"), list):
        raise ExchangeError("unexpected answer from Binance")
    out: dict[str, float] = {}
    for b in res["balances"]:
        try:
            amount = float(b.get("free") or 0) + float(b.get("locked") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if amount > 1e-12:
            asset = binance_asset(str(b.get("asset") or ""))
            out[asset] = out.get(asset, 0.0) + amount
    return out


_KRAKEN_NAMES = {"XBT": "BTC", "XDG": "DOGE"}


def kraken_asset(code: str) -> str:
    """Kraken's own codes -> the usual ones: XXBT / XBT.M = BTC, XETH = ETH, ZEUR = EUR, DOT.S = DOT."""
    c = code.split(".", 1)[0].upper()
    if len(c) == 4 and c[0] in "XZ":
        c = c[1:]
    return _KRAKEN_NAMES.get(c, c)


def kraken_balances(keys: dict[str, str], http: Http = _http, now_ms: Callable[[], int] = lambda: int(time.time() * 1000)) -> dict[str, float]:
    """coin -> amount of the Kraken account (staked and earning variants of a coin are added to the coin)."""
    key, secret = keys.get("api_key", ""), keys.get("private_key", "")
    if not key or not secret:
        raise ExchangeError("the API key or the private key is missing")
    path, nonce = "/0/private/Balance", str(now_ms())
    post = urllib.parse.urlencode({"nonce": nonce})
    try:
        sign = kraken_sign(secret, path, nonce, post)
    except ValueError:
        raise ExchangeError("the private key does not look like a Kraken private key") from None
    netlog.log("api.kraken.com", "Kraken")
    res = http(urllib.request.Request("https://api.kraken.com" + path, data=post.encode(), method="POST",
                                      headers={"API-Key": key, "API-Sign": sign,
                                               "Content-Type": "application/x-www-form-urlencoded"}))
    if not isinstance(res, dict):
        raise ExchangeError("unexpected answer from Kraken")
    if res.get("error"):
        raise ExchangeError("Kraken said: " + ", ".join(str(x) for x in res["error"])[:160])
    out: dict[str, float] = {}
    for code, raw in (res.get("result") or {}).items():
        try:
            amount = float(raw)
        except (TypeError, ValueError):
            continue
        if amount > 1e-12:
            asset = kraken_asset(str(code))
            out[asset] = out.get(asset, 0.0) + amount
    return out


READERS: dict[str, Callable[[dict[str, str]], dict[str, float]]] = {"binance": binance_balances, "kraken": kraken_balances}


def block_from(balances: dict[str, float], price_of: Callable[[str], float | None]) -> CryptoBlock | None:
    holdings: list[Holding] = []
    for asset, amount in sorted(balances.items()):
        price = FIAT_EUR.get(asset) or price_of(asset)
        holdings.append(Holding(currency=asset, amount=round(amount, 10), price=price or 0.0, eur=round2(amount * price) if price else 0.0))
    if not holdings:
        return None
    holdings.sort(key=lambda h: -h["eur"])
    return CryptoBlock(ok=True, holdings=holdings, total_eur=round2(sum(h["eur"] for h in holdings)), txs={}, trades_status="none",
                       asof=now().isoformat(timespec="seconds"), source="api")


def merge(a: CryptoBlock | None, b: CryptoBlock | None) -> CryptoBlock | None:
    """Two crypto blocks as one: the same coin on two exchanges becomes one holding. `a` keeps its own fields (status of the trades, stale mark)."""
    if not a or not b:
        return a or b
    by = {h["currency"]: h for h in a.get("holdings", [])}
    for h in b.get("holdings", []):
        old = by.get(h["currency"])
        if old:
            old["amount"] = round(old["amount"] + h["amount"], 10)
            old["eur"] = round2(old["eur"] + h["eur"])
            old["price"] = old["price"] or h["price"]
        else:
            by[h["currency"]] = h
    a["holdings"] = sorted(by.values(), key=lambda h: -h["eur"])
    a["total_eur"] = round2(sum(h["eur"] for h in a["holdings"]))
    txs = a.setdefault("txs", {})
    for coin, rows in (b.get("txs") or {}).items():
        txs.setdefault(coin, []).extend(rows)
    return a


def coinbase_keys(conn: sqlite3.Connection | None) -> dict[str, str] | None:
    """The Coinbase keys typed in under Setup as the two environment variables coinbase_fetch.mjs reads; None when there are none."""
    if conn is None:
        return None
    for s in db_accounts.list_sources(conn):
        if s["source_type"] == "api" and s["connector"] == "coinbase":
            k = keystore.load(s["id"])
            if k.get("key_name") and k.get("key_secret"):
                return {"COINBASE_KEY_NAME": k["key_name"], "COINBASE_KEY_SECRET": k["key_secret"]}
    return None


def load_blocks(ctx: RunContext, conn: sqlite3.Connection, price_of: Callable[[str], float | None],
                readers: dict[str, Callable[[dict[str, str]], dict[str, float]]] | None = None) -> list[CryptoBlock]:
    """One block per active Binance / Kraken place that has keys. A place that cannot be read becomes a warning on the dashboard, the others go on."""
    out: list[CryptoBlock] = []
    for s in db_accounts.list_sources(conn):
        reader = (readers or READERS).get(s["connector"] or "") if s["source_type"] == "api" else None
        if reader is None:
            continue
        keys = keystore.load(s["id"])
        if not keys:
            ctx.add_alert("warn", f"{s['name']}: no API key stored yet - add it under Setup > Crypto.")
            continue
        try:
            block = block_from(reader(keys), price_of)
        except ExchangeError as e:
            safenet.log.warning("%s could not be read: %s", s["name"], e)
            ctx.add_alert("warn", f"{s['name']} could not be read: {e}")
            continue
        if block:
            out.append(block)
    return out


def test_source(conn: sqlite3.Connection, source_id: Any, readers: dict[str, Callable[[dict[str, str]], dict[str, float]]] | None = None,
                coinbase: Callable[..., dict[str, Any]] = coinbase_api.fetch) -> dict[str, Any]:
    """Tries one API place right now (v1.22) and says in one plain sentence what came back: {ok, text}. Nothing is stored."""
    src = next((s for s in db_accounts.list_sources(conn, active_only=False) if s["id"] == source_id and s["source_type"] == "api"), None)
    if src is None:
        raise ValueError("this place is not in your list (any more)")
    con = connectors.BY_ID.get(src["connector"] or "")
    if con is None or not con["ready"]:
        return {"ok": False, "text": "reading through this service is not switched on yet"}
    keys = keystore.load(src["id"])
    try:
        if con["id"] == "coinbase":
            import os
            name = keys.get("key_name") or os.environ.get("COINBASE_KEY_NAME", "")
            secret = keys.get("key_secret") or os.environ.get("COINBASE_KEY_SECRET", "")
            if not (name and secret):
                return {"ok": False, "text": "no API key stored yet"}
            got = coinbase(name, secret, transactions=False)
            coins, total = len(got.get("holdings", [])), got.get("total_eur")
            return {"ok": True, "text": f"connection works: {coins} coin{'' if coins == 1 else 's'} found" + (", about " + f"{total:,.0f}".replace(",", ".") + " EUR" if total else "")}
        if not keys:
            return {"ok": False, "text": "no API key stored yet"}
        coins = len((readers or READERS)[con["id"]](keys))
        return {"ok": True, "text": f"connection works: {coins} coin{'' if coins == 1 else 's'} found"}
    except (ExchangeError, coinbase_api.CoinbaseError) as e:
        return {"ok": False, "text": str(e)}

"""
WealthView - watch list: shares you follow but do not own (data/watchlist.json), their live Yahoo prices, and the editable settings.

Used by server.py (/api/watch, /api/watch/set, /api/settings, /api/settings/set). Nothing here touches the depot or the database.
"""
from __future__ import annotations
from typing import Any
import json
import re
import threading
import time
import urllib.parse
from ...common import config, fileio, paths, safenet
from . import quotes

MAX_ITEMS = 30
QUOTE_TTL_S = 20
_SYM = re.compile(r"^[A-Za-z0-9.\-=^]{1,15}$")
_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"t": 0.0, "v": None}


def _file() -> Any:
    return paths.data_path("watchlist.json")


def load() -> list[dict[str, str]]:
    try:
        raw = json.loads(_file().read_text("utf-8"))
    except (OSError, ValueError):
        return []
    return [{"sym": str(x["sym"]), "name": str(x.get("name") or x["sym"])} for x in raw if isinstance(x, dict) and x.get("sym")]


def _save(items: list[dict[str, str]]) -> None:
    fileio.write_atomic(_file(), json.dumps(items, ensure_ascii=False, indent=1) + "\n")
    _CACHE["t"] = 0.0


def find(q: str) -> list[dict[str, str]]:
    """Yahoo search: shares and ETFs that match a name, ticker or ISIN -> [{sym, name, exch}]"""
    try:
        j = safenet.fetch_json(quotes.YAHOO_SEARCH + urllib.parse.quote(q) + "&quotesCount=8&newsCount=0")
        return [{"sym": x["symbol"], "name": x.get("shortname") or x.get("longname") or x["symbol"], "exch": x.get("exchDisp") or ""}
                for x in j.get("quotes", []) if x.get("quoteType") in ("EQUITY", "ETF") and x.get("symbol")]
    except (*safenet.NET_ERRORS, KeyError, TypeError, AttributeError) as exc:
        safenet.swallowed("watchlist.find", exc)
        return []


def action(body: dict[str, Any]) -> dict[str, Any]:
    act, q = str(body.get("action") or ""), str(body.get("sym") or body.get("q") or "").strip()[:80]
    items = load()
    if act == "find":
        return {"ok": True, "found": find(q) if q else []}
    if act == "delete":
        _save([x for x in items if x["sym"] != q])
        return {"ok": True}
    if act != "add" or not q:
        return {"ok": False, "error": "nothing to do"}
    if len(items) >= MAX_ITEMS:
        return {"ok": False, "error": f"at most {MAX_ITEMS} shares to watch"}
    sym, name = q.upper(), str(body.get("name") or "").strip()[:80]
    meta: dict[str, Any] | None = None
    if _SYM.match(q) and q == q.upper():             # typed as a ticker (capitals, e.g. ORA.PA): try it as it is; "Orange" goes to the name search
        try:
            meta, _, _ = quotes.ychart(sym)
        except quotes.MARKET_ERRORS as exc:
            safenet.swallowed("watchlist.add", exc, routine=True)
    if meta is None:                                 # a company name or ISIN: ask Yahoo which share it is
        for hit in find(q):
            try:
                meta, _, _ = quotes.ychart(hit["sym"])
                sym, name = hit["sym"], name or hit["name"]
                break
            except quotes.MARKET_ERRORS as exc:
                safenet.swallowed("watchlist.add", exc, routine=True)
    if meta is None and _SYM.match(q):               # lower-case ticker after all (e.g. "sap.de")
        try:
            meta, _, _ = quotes.ychart(sym)
        except quotes.MARKET_ERRORS as exc:
            safenet.swallowed("watchlist.add", exc, routine=True)
    if meta is None:
        return {"ok": False, "error": "no share found for \"" + q + "\" - try the ticker (e.g. ORA.PA) or the full company name"}
    if any(x["sym"] == sym for x in items):
        return {"ok": False, "error": sym + " is already on the list"}
    items.append({"sym": sym, "name": name or str(meta.get("shortName") or meta.get("longName") or sym)})
    _save(items)
    return {"ok": True, "sym": sym}


def prices() -> dict[str, Any]:
    """live price (EUR), day change and trade time of every watched share; cached for QUOTE_TTL_S; one dead symbol never stops the rest"""
    with _LOCK:
        if _CACHE["v"] is not None and time.time() - _CACHE["t"] < QUOTE_TTL_S:
            return _CACHE["v"]
        out = []
        for it in load():
            row: dict[str, Any] = {"sym": it["sym"], "name": it["name"], "price_eur": None, "cur": None, "chg_pct": None, "t": None}
            try:
                meta, _, _ = quotes.ychart(it["sym"])
                cur, p, prev = meta.get("currency") or "EUR", meta.get("regularMarketPrice"), meta.get("chartPreviousClose") or meta.get("previousClose")
                if p is not None:
                    row.update(cur=cur, price_eur=quotes.to_eur(float(p), cur), t=meta.get("regularMarketTime"),
                               chg_pct=(float(p) / float(prev) - 1) * 100 if prev else None)
            except quotes.MARKET_ERRORS as exc:
                safenet.swallowed("watchlist.prices", exc, routine=True)
            out.append(row)
        _CACHE["t"], _CACHE["v"] = time.time(), {"ok": True, "items": out}
        return _CACHE["v"]


# ---------------------------------------------------------------- settings: the few config.json values worth changing here
# key -> (label, lowest, highest, whole number?, hint)
SETTINGS: dict[str, tuple[str, float, float, bool, str]] = {
    "refresh_minutes": ("Full refresh every, minutes", 5, 240, True, "how often the files are re-read"),
    "tax.rate_pct": ("Capital gains tax, %", 0, 60, False, "used for the tax estimates (26,375 = 25 % + solidarity surcharge)"),
    "tax.allowance_eur": ("Saver's allowance, EUR", 0, 100000, False, "Sparer-Pauschbetrag (1.000 single, 2.000 couple)"),
    "thresholds.giro_min_eur": ("Current account: warn below, EUR", 0, 1000000, False, "alert when a current account falls under this"),
    "thresholds.card_max_eur": ("Card: warn above, EUR", 0, 1000000, False, "alert when a card balance grows past this"),
    "oneoff_threshold_eur": ("One-off booking from, EUR", 100, 1000000, False, "bookings this big are shown as one-offs"),
}


def _dig(cfg: dict[str, Any], path: str) -> Any:
    cur: Any = cfg
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def settings_state() -> dict[str, Any]:
    cfg = config.load_config()
    return {"ok": True, "fields": [{"key": k, "label": v[0], "min": v[1], "max": v[2], "int": v[3], "hint": v[4],
                                    "value": _dig(cfg, k) if _dig(cfg, k) is not None else config.cfg_value(k)} for k, v in SETTINGS.items()]}


def settings_set(body: dict[str, Any]) -> dict[str, Any]:
    key = str(body.get("key") or "")
    if key not in SETTINGS:
        return {"ok": False, "error": "unknown setting"}
    label, lo, hi, whole, _ = SETTINGS[key]
    try:
        val = float(str(body.get("value")).replace(".", "").replace(",", ".")) if "," in str(body.get("value")) else float(str(body.get("value")))
    except ValueError:
        return {"ok": False, "error": label + ": please type a number"}
    if not lo <= val <= hi:
        return {"ok": False, "error": f"{label}: between {lo:g} and {hi:g}"}
    num: float | int = int(round(val)) if whole else val

    def put(cfg: dict[str, Any]) -> None:
        cur = cfg
        parts = key.split(".")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = num
    config.update_config(put)
    return {"ok": True}

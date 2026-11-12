"""
WealthView - market quotes: the Yahoo Finance chart/search/dividend fetchers, EUR FX conversion, monthly close series and live prices.

Used by refresh.py, positions.py, research.py and server.py.
"""
from __future__ import annotations
from typing import Any
from collections.abc import Mapping
import datetime as dt
import threading
import time
import urllib.parse
from ...common import safenet
from ...common.timeutil import axis, month_key

FX_TTL_S = 6 * 3600     # exchange rates are fetched again after this long
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
YAHOO_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search?q="

# What a market-data lookup can raise: network/parse errors (safenet.NET_ERRORS) or an answer of an unexpected shape.
MARKET_ERRORS = safenet.NET_ERRORS + (KeyError, IndexError, TypeError, AttributeError, ZeroDivisionError)


def chart_result(sym: str, rng: str, itv: str, events: str | None = None) -> dict[str, Any]:
    """The raw first result of a Yahoo chart answer (meta, timestamp, indicators and, with `events`, e.g. 'split', the events)."""
    u = YAHOO_CHART.format(sym=urllib.parse.quote(sym)) + f"?range={rng}&interval={itv}&includePrePost=false"
    if events:
        u += f"&events={events}"
    res: dict[str, Any] = safenet.fetch_json(u)["chart"]["result"][0]
    return res


def ychart(sym: str, rng: str = "5d", itv: str = "1d") -> tuple[dict[str, Any], list[int], list[float | None]]:
    res = chart_result(sym, rng, itv)
    q = (res["indicators"]["quote"][0].get("close")) or []
    return res["meta"], res.get("timestamp") or [], q


class FxRates:
    """EUR exchange rates fetched on first use and fetched again once they are older than FX_TTL_S (the server runs for days)"""

    def __init__(self) -> None:
        self._rates: dict[str, tuple[float, float]] = {}      # currency -> (rate, time fetched)
        self._lock = threading.Lock()

    def rate(self, cur: str) -> float:
        """units of `cur` per 1 EUR"""
        if cur == "EUR":
            return 1.0
        with self._lock:
            hit = self._rates.get(cur)
            if hit is None or time.time() - hit[1] > FX_TTL_S:
                meta, _, _ = ychart(f"EUR{cur}=X")
                hit = (float(meta["regularMarketPrice"]), time.time())
                self._rates[cur] = hit
            return hit[0]


_FX = FxRates()


def fx_rate(cur: str) -> float:
    """units of `cur` per 1 EUR"""
    return _FX.rate(cur)


def to_eur(price: float, cur: str) -> float:
    if cur in ("GBp", "GBX"):
        price, cur = price / 100.0, "GBP"
    return price / fx_rate(cur)


def month_key_from_timestamp(ts: float) -> str:
    return month_key(dt.datetime.fromtimestamp(ts, dt.timezone.utc))


def monthly_closes(sym: str, cur: str) -> dict[str, float]:
    """{'YYYY-MM': close in EUR (today's FX)} for the last ~10y."""
    _, ts, cl = ychart(sym, "10y", "1mo")
    out: dict[str, float] = {}
    for t, c in zip(ts, cl):
        if c is not None:
            out[month_key_from_timestamp(t)] = to_eur(float(c), cur)
    return out


def align(series: dict[str, float], fill_back: bool = True) -> list[float | None]:
    """series {'YYYY-MM': v} -> list on axis() (forward-fill; optional back-fill with first value)."""
    out: list[float | None] = []
    last = None
    first = next((series[m] for m in sorted(series)), None)
    for m in axis():
        if m in series:
            last = series[m]
        out.append(last if last is not None else (first if fill_back else None))
    return [None if v is None else round(v, 4) for v in out]


def search_syms(q: str) -> list[str]:
    try:
        j = safenet.fetch_json(YAHOO_SEARCH + urllib.parse.quote(q) + "&quotesCount=6&newsCount=0")
        return [x["symbol"] for x in j.get("quotes", []) if x.get("quoteType") in ("EQUITY", "ETF", "MUTUALFUND")]
    except (*safenet.NET_ERRORS, KeyError, TypeError, AttributeError) as exc:
        safenet.swallowed("quotes.search_syms", exc)
        return []


def try_symbol(sym: str, snap: float | None, tolerance: float) -> dict[str, Any] | None:
    """Quote for `sym` if its EUR price is within `tolerance` (fraction) of the depot export price `snap`, else None."""
    if not snap:  # no reference price in the export -> cannot validate, stay static
        return None
    meta, _, _ = ychart(sym)
    cur = meta.get("currency") or "EUR"
    p = meta.get("regularMarketPrice")
    if p is None:
        return None
    eur = to_eur(float(p), cur)
    if not (1 - tolerance <= eur / snap <= 1 + tolerance):
        return None
    return dict(sym=sym, cur=cur, price_eur=eur, t=meta.get("regularMarketTime"))


def ydiv(sym: str) -> tuple[float, str]:
    u = YAHOO_CHART.format(sym=urllib.parse.quote(sym)) + "?range=1y&interval=1d&events=div"
    res = safenet.fetch_json(u)["chart"]["result"][0]
    divs = (res.get("events") or {}).get("dividends") or {}
    tot = sum(float(v["amount"]) for v in divs.values())
    return tot, (res["meta"].get("currency") or "EUR")


def live_prices(data: Mapping[str, Any], crypto: bool = True) -> dict[str, float]:
    """Used by the server: fresh prices for symbols of the real data (EUR)."""
    out: dict[str, float] = {}
    for p in (data.get("depot") or {}).get("positions", []):
        if p.get("sym"):
            try:
                meta, _, _ = ychart(p["sym"])
                out[p["wkn"]] = round(to_eur(float(meta["regularMarketPrice"]), meta.get("currency") or "EUR"), 4)
            except (*safenet.NET_ERRORS, KeyError, IndexError, TypeError) as exc:
                safenet.swallowed("quotes.live_prices", exc)
    for h in ((data.get("crypto") or {}).get("holdings", []) if crypto else []):
        try:
            meta, _, _ = ychart(f"{h['currency']}-EUR")
            out["crypto:" + h["currency"]] = round(float(meta["regularMarketPrice"]), 6)
        except (*safenet.NET_ERRORS, KeyError, IndexError, TypeError) as exc:
            safenet.swallowed("quotes.live_prices", exc)
    return out

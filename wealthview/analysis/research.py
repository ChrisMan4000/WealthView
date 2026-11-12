"""
WEALTHVIEW - live research for ONE security (used by the position popup; called by server.py when you click a position).

 research(sym, name, wkn) -> dict with
   prices   daily closes of the last 5 years in EUR (today's exchange rate), as [[unix_ts, close], ...]
   splits   stock splits in that period [{d, ratio}]  (the popup uses them to adjust old purchases)
   metrics  trend / momentum / RSI / 52-week range computed from those prices
   analyst  consensus + price target from Yahoo Finance (None when Yahoo does not hand it out)
   news     the 3 latest headlines (Yahoo Finance, Google News as a fallback / addition)
   score    the rule-based META-SCORE 0..100 with every factor listed (education, not advice)

Everything is fetched at the moment you click (a 2-minute cache protects the sources). Nothing is written to disk.
"""
from __future__ import annotations
from typing import Any
import copy
import datetime as dt
import http.cookiejar
import json
import math
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from ..data.ingest import quotes
from ..common import safenet
from ..data.finance.categories import sector_key
from ..common.types.research import Analyst, Factor, FundProfile, MetaScore, Metrics, NewsItem, ResearchResult

MAX_CACHED = 30        # research answers kept in the short-lived cache (each holds a 5-year price list)
CRUMB_TTL_S = 3000      # a Yahoo crumb is reused for this long
PRINT_LIMIT = 4000      # characters shown by the command-line self-test

YAHOO_Q1 = "https://query1.finance.yahoo.com"
YAHOO_Q2 = "https://query2.finance.yahoo.com"
YAHOO_COOKIE_URL = "https://fc.yahoo.com"


class _CrumbSession:
    """the Yahoo cookie opener and crumb, reused for CRUMB_TTL_S"""
    t: float = 0
    opener: urllib.request.OpenerDirector | None = None
    crumb: str = ""


class _ResultCache:
    """short-lived cache of research() answers, keyed by (symbol, name, wkn)"""

    def __init__(self) -> None:
        self._items: dict[tuple, tuple] = {}
        self._lock = threading.Lock()        # the server answers requests in parallel threads

    def get(self, key: tuple) -> Any:
        with self._lock:
            return self._items.get(key)

    def put(self, key: tuple, value: Any) -> None:
        entry = (time.time(), copy.deepcopy(value))
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = entry
            while len(self._items) > MAX_CACHED:      # dicts keep insertion order: drop the oldest entry
                del self._items[next(iter(self._items))]


_CACHE = _ResultCache()
_CRUMB = _CrumbSession()


# ------------------------------------------------------------------ prices
def _chart(sym: str) -> tuple[dict[str, Any], list[list[float]], list[dict[str, Any]]]:
    res = quotes.chart_result(sym, "5y", "1d", "split")
    meta = res["meta"]
    ts = res.get("timestamp") or []
    cl = (res["indicators"]["quote"][0].get("close")) or []
    cur = meta.get("currency") or "EUR"
    px: list[list[float]] = [[int(t), round(quotes.to_eur(float(c), cur), 4)] for t, c in zip(ts, cl) if c is not None]
    spl: list[dict[str, Any]] = []
    for s in ((res.get("events") or {}).get("splits") or {}).values():
        try:
            spl.append(dict(d=dt.datetime.fromtimestamp(s["date"], dt.timezone.utc).date().isoformat(),
                            ratio=float(s["numerator"]) / float(s["denominator"])))
        except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError, OSError) as exc:
            safenet.swallowed("research._chart", exc)
    spl.sort(key=lambda x: x["d"])
    return meta, px, spl


def _search(q: str, news: int = 6) -> dict[str, Any]:
    u = (YAHOO_Q2 + "/v1/finance/search?q=" + urllib.parse.quote(q) +
         f"&quotesCount=4&newsCount={news}&listsCount=0")
    result: dict[str, Any] = safenet.fetch_json(u)
    return result


def _find_symbol(name: str) -> str | None:
    found = quotes.search_syms(name)       # equities, ETFs and funds only
    return found[0] if found else None


# ----------------------------------------------------------------- metrics
def _sma(v: list[float], n: int) -> float | None:
    return sum(v[-n:]) / n if len(v) >= n else None


def _rsi(v: list[float], n: int = 14) -> float | None:
    if len(v) <= n:
        return None
    g = l = 0.0
    for i in range(1, n + 1):
        d = v[i] - v[i - 1]
        g += max(d, 0)
        l += max(-d, 0)
    g /= n
    l /= n
    for i in range(n + 1, len(v)):
        d = v[i] - v[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def _ret(v: list[float], days: int) -> float | None:
    return (v[-1] / v[-1 - days] - 1) * 100 if len(v) > days and v[-1 - days] else None


def metrics(px: list[list[float]]) -> Metrics | None:
    v = [p[1] for p in px]
    if len(v) < 30:
        return None
    last = v[-1]
    y = v[-252:]
    dr = [math.log(v[i] / v[i - 1]) for i in range(max(1, len(v) - 252), len(v)) if v[i - 1] > 0 and v[i] > 0]
    mean = sum(dr) / len(dr) if dr else 0
    vol = (math.sqrt(sum((x - mean) ** 2 for x in dr) / max(1, len(dr) - 1)) * math.sqrt(252) * 100) if dr else None
    return Metrics(last=last, sma50=_sma(v, 50), sma200=_sma(v, 200), r1m=_ret(v, 21), r6m=_ret(v, 126), r12m=_ret(v, 252),
                   rsi=_rsi(v), hi52=max(y), lo52=min(y), from_hi=(last / max(y) - 1) * 100, vol=vol)


# ----------------------------------------------------------------- analyst
def _yahoo_session() -> tuple[urllib.request.OpenerDirector, str]:
    now = time.time()
    if _CRUMB.opener is not None and now - _CRUMB.t < CRUMB_TTL_S:
        return _CRUMB.opener, _CRUMB.crumb
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        safenet.open_with(op, urllib.request.Request(YAHOO_COOKIE_URL, headers=safenet.DEFAULT_HEADERS), 10)
    except safenet.NET_ERRORS as exc:
        safenet.swallowed("research._yahoo_session", exc)  # answers 404 but sets the cookie
    crumb = safenet.fetch_text(YAHOO_Q1 + "/v1/test/getcrumb", 10, op).strip()
    if not crumb or "<" in crumb:
        raise RuntimeError("no crumb")
    _CRUMB.t, _CRUMB.opener, _CRUMB.crumb = now, op, crumb
    return op, crumb


def analyst(sym: str) -> Analyst | None:
    try:
        op, crumb = _yahoo_session()
        u = (f"{YAHOO_Q2}/v10/finance/quoteSummary/{urllib.parse.quote(sym)}"
             f"?modules=financialData,recommendationTrend&crumb={urllib.parse.quote(crumb)}")
        res = safenet.fetch_json(u, 12, op)["quoteSummary"]["result"][0]
        fd = res.get("financialData") or {}
        raw = lambda k: (fd.get(k) or {}).get("raw")
        out = Analyst(rec_mean=raw("recommendationMean"), rec_key=fd.get("recommendationKey"), n=raw("numberOfAnalystOpinions"),
                   target=raw("targetMeanPrice"), target_hi=raw("targetHighPrice"), target_lo=raw("targetLowPrice"),
                   cur=fd.get("financialCurrency"), price_native=raw("currentPrice"))
        if out["rec_mean"] is None and out["target"] is None:
            return None
        tr = (res.get("recommendationTrend") or {}).get("trend") or []
        if tr:
            t0 = tr[0]
            out["trend"] = {k: t0.get(k) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
        if out["target"] and out["price_native"]:
            out["upside"] = (out["target"] / out["price_native"] - 1) * 100
        return out
    except Exception as exc:    # broad on purpose: the analyst box is optional, any failure just means "no data"
        safenet.swallowed("research.analyst", exc)
        return None


# ------------------------------------------------------------ profile (cost, country, sectors, top holdings)
def _sector_key(s: str | None) -> str | None:
    """the shared sector spelling (categories.sector_key); None when there is no sector"""
    return sector_key(s) or None


def _sector_weights(th: dict[str, Any]) -> dict[str | None, float]:
    weights: dict[str | None, float] = {}
    for item in th.get("sectorWeightings") or []:
        for k, v in item.items():
            if isinstance(v, dict) and v.get("raw") is not None:
                weights[_sector_key(k)] = v["raw"]
    return weights


def _top_holdings(th: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"symbol": h.get("symbol"), "name": h.get("holdingName"), "weight": (h.get("holdingPercent") or {}).get("raw")}
            for h in (th.get("holdings") or [])[:10] if (h.get("holdingPercent") or {}).get("raw") is not None]


def parse_profile(res: dict[str, Any]) -> FundProfile:
    """quoteSummary result[0] -> {ter (% per year), country, sector, currency, sector_weights, top_holdings}.
    Funds carry sector weights + top holdings, shares carry country + sector; missing data stays None / empty."""
    ap, fp, pr = res.get("assetProfile") or {}, res.get("fundProfile") or {}, res.get("price") or {}
    ter = ((fp.get("feesExpensesInvestment") or {}).get("annualReportExpenseRatio") or {}).get("raw")
    if ter is None:
        ter = ((res.get("defaultKeyStatistics") or {}).get("annualReportExpenseRatio") or {}).get("raw")
    th = res.get("topHoldings") or {}
    return FundProfile(ter=ter * 100.0 if ter is not None else None, country=ap.get("country"), sector=_sector_key(ap.get("sector")),
                       currency=pr.get("currency"), sector_weights=_sector_weights(th), top_holdings=_top_holdings(th))


def fund_profile(sym: str) -> FundProfile | None:
    try:
        op, crumb = _yahoo_session()
        u = (f"{YAHOO_Q2}/v10/finance/quoteSummary/{urllib.parse.quote(sym)}"
             f"?modules=assetProfile,fundProfile,topHoldings,price,defaultKeyStatistics&crumb={urllib.parse.quote(crumb)}")
        return parse_profile(safenet.fetch_json(u, 12, op)["quoteSummary"]["result"][0])
    except Exception as exc:       # broad on purpose: the fund profile is optional, any failure just means "no profile"
        safenet.swallowed("research.fund_profile", exc)
        return None


# -------------------------------------------------------------------- news
GOOD = re.compile(r"\b(beat|beats|surge|surges|soar|soars|record|upgrade|upgraded|raises|raised|growth|jump|jumps|rally|rallies|wins|win|strong|profit|boost|bullish|outperform|expands|partnership|approval|approved)\b", re.I)
BAD = re.compile(r"\b(miss|misses|plunge|plunges|slump|slumps|falls|fall|drop|drops|downgrade|downgraded|cut|cuts|lawsuit|probe|investigation|recall|warning|warns|weak|loss|losses|bearish|underperform|fraud|ban|tariff|layoffs|delay|delays)\b", re.I)


def _sent(title: str) -> int:
    return len(GOOD.findall(title)) - len(BAD.findall(title))


def _rss(q: str) -> list[NewsItem]:
    u = safenet.GOOGLE_NEWS_RSS + urllib.parse.quote(q) + safenet.GOOGLE_NEWS_PARAMS
    out: list[NewsItem] = []
    for it in safenet.rss_items(safenet.parse_xml(safenet.fetch_text(u, 12))):
        try:
            t = dt.datetime.strptime(it["pubDate"], "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=dt.timezone.utc).timestamp()
        except (TypeError, ValueError):
            t = 0
        out.append(NewsItem(title=it["title"], publisher=it["source"] or "Google News", url=it["link"], t=int(t)))
    return out


def news(sym: str, name: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        for n in _search(sym or name, 8).get("news", []):
            items.append(NewsItem(title=n.get("title"), publisher=n.get("publisher"), url=n.get("link"), t=n.get("providerPublishTime") or 0))
    except (*safenet.NET_ERRORS, AttributeError, TypeError) as exc:
        safenet.swallowed("research.news", exc)
    if len(items) < 3:
        try:
            items += _rss(f'"{name}" stock')
        except safenet.NET_ERRORS as exc:
            safenet.swallowed("research.news", exc)
    return _newest_unique(items)


def _newest_unique(items: list[NewsItem]) -> list[NewsItem]:
    """the 3 newest news items that have a title and a link, without duplicate titles, each with its sentiment ('sent')"""
    seen: set[str] = set()
    out: list[NewsItem] = []
    for n in sorted(items, key=lambda x: -(x.get("t") or 0)):
        k = re.sub(r"\W+", "", (n.get("title") or "").lower())[:60]
        title = n.get("title")
        if title and n.get("url") and k not in seen:
            seen.add(k)
            n["sent"] = _sent(title)
            out.append(n)
    return out[:3]


# ------------------------------------------------------------------- score
def _clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def _trend_factor(m: Metrics) -> Factor:
    """the 'Trend' factor: 200-day average 9 points, 50-day average 6, golden cross (50 over 200) 5; max 20"""
    pts = 0.0
    txt = []
    if m["sma200"]:
        ab = m["last"] > m["sma200"]
        pts += 9 if ab else 0
        txt.append("above 200-day" if ab else "below 200-day")
    if m["sma50"]:
        ab = m["last"] > m["sma50"]
        pts += 6 if ab else 0
        txt.append("above 50-day" if ab else "below 50-day")
    if m["sma50"] and m["sma200"]:
        gc = m["sma50"] > m["sma200"]
        pts += 5 if gc else 0
    return Factor(name="Trend", text=", ".join(txt), pts=pts, max=20)


def _technical_factors(m: Metrics) -> list[Factor]:
    """trend, momentum, RSI and distance-to-high factors from the price metrics"""
    F: list[Factor] = [_trend_factor(m)]
    r6, r12 = m.get("r6m"), m.get("r12m")
    if r6 is not None and r12 is not None:
        p = 20 * (0.5 * _clamp((r6 + 20) / 60) + 0.5 * _clamp((r12 + 25) / 90))
        F.append(dict(name="Momentum", text=f"6 m {r6:+.0f} % · 12 m {r12:+.0f} %", pts=p, max=20))
    rsi = m["rsi"]
    if rsi is not None:
        p = 10 * (1 - _clamp(abs(rsi - 45) / 40)) if rsi >= 30 else 10
        F.append(dict(name="RSI (14)", text=f"{rsi:.0f}" + (" · oversold" if rsi < 30 else " · overbought" if rsi > 70 else ""), pts=p, max=10))
    dd = -m["from_hi"]
    p = 10 * (1 - _clamp(abs(dd - 12) / 45))
    F.append(dict(name="Distance to 52 w high", text=f"{m['from_hi']:+.0f} %", pts=p, max=10))
    return F


def _analyst_factors(an: Analyst) -> list[Factor]:
    """consensus and price-target factors from the analyst data"""
    F: list[Factor] = []
    rec_mean, upside = an.get("rec_mean"), an.get("upside")
    if rec_mean is not None:
        p = 15 * _clamp((5 - rec_mean) / 4)
        F.append(dict(name="Analyst consensus", text=f"{rec_mean:.1f}/5 ({(an.get('rec_key') or '').replace('_', ' ')})" + (f" · {an['n']} analysts" if an.get("n") else ""), pts=p, max=15))
    if upside is not None:
        p = 10 * _clamp(0.5 + upside / 60)
        F.append(dict(name="Price target", text=f"{upside:+.0f} % to mean target", pts=p, max=10))
    return F


def _verdict(tot: float) -> str:
    return "STRONG BUY" if tot >= 72 else "BUY" if tot >= 60 else "HOLD" if tot >= 45 else "REDUCE" if tot >= 33 else "SELL"


def meta_score(m: Metrics | None, an: Analyst | None, nw: list[NewsItem] | None) -> MetaScore | None:
    """Rule-based composite 0..100. Each factor: name, text, pts, max. Missing factors are left out and the rest is rescaled."""
    F = _technical_factors(m) if m else []
    if an:
        F += _analyst_factors(an)
    if nw:
        s = sum(n["sent"] for n in nw)
        p = 5 + 5 * _clamp(s / 3, -1, 1)
        F.append(dict(name="News tone", text=("positive" if s > 0 else "negative" if s < 0 else "neutral") + f" ({len(nw)} headlines)", pts=p, max=10))
    mx = sum(f["max"] for f in F)
    if not mx:
        return None
    tot = sum(f["pts"] for f in F) / mx * 100
    for f in F:
        f["pts"] = round(f["pts"], 1)
    return MetaScore(total=round(tot), verdict=_verdict(tot), factors=F, coverage=round(mx))


# -------------------------------------------------------------------- main
def _resolve_symbol(sym: str, name: str, out: ResearchResult) -> str | None:
    """the stored symbol, else a symbol matched by name (noted in out["notes"]); None when neither exists"""
    if sym:
        return sym
    found = _find_symbol(re.sub(r"\(.*?\)", "", name or "").strip())
    out["sym"] = found
    if found:
        out["notes"].append(f"No quote symbol was stored for this position; matched '{found}' by name.")
    return found


def _price_history(sym: str | None, out: ResearchResult) -> tuple[list[Any], list[Any], dict[str, Any]]:
    """-> (prices, splits, meta); a failure is only noted in out["notes"]"""
    px: list[list[float]] = []
    spl: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    if sym:
        try:
            meta, px, spl = _chart(sym)
        except (*safenet.NET_ERRORS, KeyError, IndexError, TypeError, ZeroDivisionError) as e:
            out["notes"].append("Price history not available: " + str(e))
    else:
        out["notes"].append("No market symbol found (e.g. a fund without a listing): no price research possible.")
    return px, spl, meta


def research(sym: str, name: str, wkn: str = "") -> ResearchResult:
    key = (sym or "", name or "", wkn or "")
    c = _CACHE.get(key)
    if c and time.time() - c[0] < 120:
        return copy.deepcopy(c[1])     # callers get their own copy: the cached entry is never handed out
    out = ResearchResult(ok=True, sym=sym, name=name, t=int(time.time()), notes=[])
    found = _resolve_symbol(sym, name, out)
    px, spl, meta = _price_history(found, out)
    out["prices"] = px
    out["splits"] = spl
    out["currency"] = meta.get("currency")
    out["long_name"] = meta.get("longName") or meta.get("shortName")
    out["metrics"] = metrics(px) if px else None
    out["analyst"] = analyst(found) if found else None
    nm = re.sub(r"\(.*?\)", "", out.get("long_name") or name or "").strip() or (name or "")
    out["news"] = news(found or "", nm)
    out["score"] = meta_score(out["metrics"], out["analyst"], out["news"])
    _CACHE.put(key, out)
    return out


if __name__ == "__main__":
    r = research(sys.argv[1] if len(sys.argv) > 1 else "ASML.AS", sys.argv[2] if len(sys.argv) > 2 else "ASML")
    shown: dict[str, Any] = dict(r, prices=f"[{len(r['prices'])} points]")      # do not print every price
    print(json.dumps(shown, indent=1, ensure_ascii=False)[:PRINT_LIMIT])

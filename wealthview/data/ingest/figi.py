"""WealthView v1.22: from a German securities number (WKN) to market symbols. A bank export names a security by its WKN and an abbreviated name
("Lgue-Hydr.Eco. Dla"); the quote service knows neither. OpenFIGI (api.openfigi.com, free, no key) maps the WKN to the security's real name and
its tickers per stock exchange; those become candidate symbols that positions.resolve_positions() then checks against the export price.
Only the WKNs are sent - never quantities, values or names. Standard library only."""
from __future__ import annotations
import json, urllib.request
from typing import Any, Callable

from ...common import netlog, safenet

URL = "https://api.openfigi.com/v3/mapping"
BATCH = 10            # jobs per request without an API key
TIMEOUT = 15
# exchange code of the listing -> ending of the quote symbol, in the order they are tried (euro markets first: the export price is in EUR)
SUFFIX: tuple[tuple[str, str], ...] = (
    ("GY", ".DE"), ("GR", ".DE"), ("GF", ".F"), ("GM", ".MU"), ("GS", ".SG"), ("GD", ".DU"), ("GH", ".HM"), ("GB", ".BE"),
    ("NA", ".AS"), ("FP", ".PA"), ("IM", ".MI"), ("SM", ".MC"), ("BB", ".BR"), ("AV", ".VI"), ("FH", ".HE"), ("ID", ".IR"),
    ("LN", ".L"), ("SW", ".SW"), ("SE", ".SW"), ("US", ""), ("UN", ""), ("UW", ""), ("UQ", ""), ("UA", ""), ("UP", ""),
    ("HK", ".HK"), ("AT", ".AX"), ("AU", ".AX"), ("CT", ".TO"), ("CN", ".TO"), ("JT", ".T"), ("SS", ".ST"), ("DC", ".CO"), ("NO", ".OL"),
)
MAX_SYMBOLS = 8
Post = Callable[[list[dict[str, str]]], Any]


def _post(jobs: list[dict[str, str]]) -> Any:
    netlog.log("api.openfigi.com", "OpenFIGI")
    req = urllib.request.Request(URL, data=json.dumps(jobs).encode(), headers={"Content-Type": "application/json", **safenet.DEFAULT_HEADERS})
    with safenet.urlopen(req, TIMEOUT) as r:
        return json.loads(r.read(safenet.MAX_BYTES).decode("utf-8", "replace"))


def nice_name(name: str) -> str:
    """'L&G HYDROGEN ECONOMY ETF' -> 'L&G Hydrogen Economy ETF' (short all-capital words such as ETF, ADR, NV, AI stay)"""
    words = []
    for w in str(name or "").split():
        words.append(w if (len(w) <= 3 and w.isupper()) or not w.isupper() else w[:1] + w[1:].lower())
    return " ".join(words)


def symbols_from(rows: list[dict[str, Any]]) -> list[str]:
    """Candidate quote symbols from the listings OpenFIGI returned for one security, best market first, without doubles."""
    by_exch: dict[str, str] = {}
    for r in rows:
        ex, tick = str(r.get("exchCode") or ""), str(r.get("ticker") or "")
        if ex and tick and " " not in tick and ex not in by_exch:
            by_exch[ex] = tick.replace("/", "-")
    out: list[str] = []
    for ex, suffix in SUFFIX:
        if ex in by_exch and by_exch[ex] + suffix not in out:
            out.append(by_exch[ex] + suffix)
    return out[:MAX_SYMBOLS]


def lookup(wkns: list[str], post: Post = _post) -> dict[str, dict[str, Any]]:
    """{wkn: {name, symbols}} for the WKNs OpenFIGI knows. A failed request ends the lookup with what was found so far (never raises)."""
    out: dict[str, dict[str, Any]] = {}
    todo = [w for w in dict.fromkeys(wkns) if w]
    for i in range(0, len(todo), BATCH):
        part = todo[i:i + BATCH]
        try:
            res = post([{"idType": "ID_WERTPAPIER", "idValue": w} for w in part])
        except (*safenet.NET_ERRORS, TypeError) as exc:
            safenet.swallowed("figi.lookup", exc)
            break
        if not isinstance(res, list):
            break
        for w, item in zip(part, res):
            rows = item.get("data") if isinstance(item, dict) else None
            if not isinstance(rows, list) or not rows:
                continue
            rows = [r for r in rows if isinstance(r, dict)]
            equity = [r for r in rows if r.get("marketSector") == "Equity"]      # shares, ETFs and funds; certificates and bonds have no quote symbol
            if equity:
                out[w] = {"name": nice_name(str(equity[0].get("name") or "")), "symbols": symbols_from(equity)}
    return out

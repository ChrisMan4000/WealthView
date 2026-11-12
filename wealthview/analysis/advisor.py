"""Chat helpers (v1.15): a compact summary of the whole portfolio for the model, and web look-ups the APP performs for it.

Only the search words leave the PC (a public search page is fetched); portfolio figures are never sent anywhere except the local model.
"""
from __future__ import annotations
from typing import Any
import html, re, urllib.parse
from ..common import config, safenet
from ..common.profile import load_profile

_RESULT = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?(?:class="result__snippet"[^>]*>(.*?)</a>)?', re.S)
_TAGS = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return html.unescape(_TAGS.sub("", s or "")).strip()


def _real_url(href: str) -> str:
    """DuckDuckGo wraps result links as //duckduckgo.com/l/?uddg=<url>"""
    q = urllib.parse.urlparse(href)
    inner = urllib.parse.parse_qs(q.query).get("uddg")
    return inner[0] if inner else href


def parse_results(page: str, limit: int = 5) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for href, title, snip in _RESULT.findall(page):
        url = _real_url(html.unescape(href))
        if url.startswith("//"):
            url = "https:" + url
        if safenet.is_web_link(url):
            out.append(dict(title=_text(title)[:160], url=url, snippet=_text(snip)[:300]))
        if len(out) >= limit:
            break
    return out


def web_search(query: str, limit: int = 5) -> list[dict[str, str]]:
    """-> [{title, url, snippet}]; [] when the search page cannot be reached"""
    q = " ".join(str(query).split())[:120]
    if not q:
        return []
    try:
        page = safenet.fetch_text("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q), timeout=12, headers={"User-Agent": "Mozilla/5.0"})
    except (*safenet.NET_ERRORS, ValueError) as e:
        safenet.swallowed("advisor.web_search", e, routine=True)
        return []
    return parse_results(page, limit)


def _eur(v: Any) -> str:
    try:
        return f"{float(v):,.0f} EUR"
    except (TypeError, ValueError):
        return "n/a"


_COUNTRIES = {"DE": "Germany"}


def owner_line() -> str:
    """'Owner: <name>, <filing>, <income>, <church tax>, <country>.' built from config.json (display_name, tax) and the profile's
    tax country. Clauses the config does not state are left out, never invented; no name means "the user"."""
    tax = config.load_config().get("tax") or {}
    parts = [config.owner_display() or "the user"]
    if tax.get("filing"):
        parts.append(str(tax["filing"]))
    if "other_income_eur" in tax:
        parts.append("no income" if not tax["other_income_eur"] else f"other income {_eur(tax['other_income_eur'])}")
    if "church_tax" in tax:
        parts.append("church tax" if tax["church_tax"] else "no church tax")
    cc = str(load_profile().tax_country or "").upper()
    if cc:
        parts.append(_COUNTRIES.get(cc, cc))
    return "Owner: " + ", ".join(parts) + "."


def portfolio_summary(d: dict[str, Any]) -> str:
    """Plain-text overview of data.json for the model: totals, allocation, positions, crypto, World Fund, apartment, loan, tax."""
    if not d:
        return "(no portfolio data loaded)"
    t = d.get("totals") or {}
    L = [f"{owner_line()} Net worth {_eur(t.get('net'))}, after tax {_eur(t.get('net_after_tax'))}, "
         f"assets {_eur(t.get('assets'))}, liabilities {_eur(t.get('liabilities'))}."]
    groups = t.get("groups") or []
    tot = sum(float(g.get("v") or 0) for g in groups) or 1.0
    L.append("Allocation: " + ", ".join(f"{g['k']} {_eur(g['v'])} ({100 * float(g['v']) / tot:.0f}%)" for g in groups))
    dep = d.get("depot") or {}
    pos = sorted(dep.get("positions") or [], key=lambda p: -(p.get("value") or 0))[:15]
    if pos:
        L.append("Securities (top): " + "; ".join(f"{p.get('name')} {_eur(p.get('value'))} gain {_eur(p.get('gain'))}" for p in pos))
    cb = d.get("crypto") or {}
    if cb:
        L.append(f"Crypto total {_eur(cb.get('total_eur'))}: " + ", ".join(f"{c.get('currency')} {_eur(c.get('eur'))}" for c in (cb.get("coins") or [])[:8]))
    wf = d.get("worldfund") or {}
    if wf.get("personal"):
        p = wf["personal"]
        L.append(f"World Fund (private equity): NAV {_eur(p.get('nav'))}, paid in {_eur(p.get('paid_in'))}.")
    ap = d.get("apartment") or {}
    if ap:
        L.append(f"Apartment {ap.get('address', '')}: value {_eur(ap.get('value_used'))}, bought {ap.get('purchase_date')} for {_eur(ap.get('purchase_price'))}, {ap.get('sqm')} sqm.")
    ln = d.get("loan")
    if ln:
        L.append(f"Family loan: balance {_eur(ln.get('balance'))}, {_eur(ln.get('monthly'))}/month, payoff {ln.get('payoff')}.")
    tx = d.get("tax") or {}
    if tx.get("method"):
        L.append(f"Tax if sold today: {_eur(tx.get('tax'))} ({tx.get('method')}); tax-free headroom {_eur(tx.get('tax_free_headroom'))}.")
    sale = d.get("apartment_sale")
    if sale and "net_proceeds" in sale:
        L.append(f"Apartment sale: tax {_eur(sale.get('tax'))}, net proceeds after loan {_eur(sale.get('net_proceeds'))}.")
    return "\n".join(L)

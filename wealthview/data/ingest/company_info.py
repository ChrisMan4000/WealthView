"""
Company facts for the World Fund / wiwin pop-ups, fetched when you click (Wikidata + the company's own site +
Google News). Public information only - only the company name and its web address leave this PC.
company_profile() NEVER raises: whatever cannot be found is None / [] and found[field] is False, so the pop-up says
"not found" instead of guessing. Facts are cached for 7 days, news for 1 hour (company_cache.json).
"""
from __future__ import annotations
from typing import Any, Callable
import datetime as dt
import email.utils
import html
import json
import re
import time
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from ...common import fileio
from ...common import safenet
from ...common.safenet import is_web_link, safe_web   # the public-address checks live in safenet (also used by logos_online)
from ...common.timeutil import DAY_S, HOUR_S
from ...common.fileio import write_atomic

WD = "https://www.wikidata.org/w/api.php?"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/"
FACTS_TTL, NEWS_TTL = 7 * DAY_S, HOUR_S


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect may not lead to a private address either (a public site could point to http://127.0.0.1/...)."""
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        if safe_web(newurl, resolve=True) is None:
            raise urllib.error.URLError("redirect to a non-public address refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_fetch(url: str) -> str:
    if safe_web(url, resolve=True) is None:
        raise ValueError("address not allowed")
    return safenet.fetch_text(url, 12, opener=urllib.request.build_opener(_PublicRedirects))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _claims(entity: dict[str, Any], pid: str) -> list[Any]:
    out: list[Any] = []
    for c in (entity.get("claims") or {}).get(pid, []):
        try:
            out.append(c["mainsnak"]["datavalue"]["value"])
        except (KeyError, TypeError) as exc:      # a claim without a main value is skipped
            safenet.swallowed("company_info._claims", exc)
    return out


_NOT_A_COMPANY = re.compile(r"\b(film|movie|album|song|single|novel|book|television|tv series|series|episode|band|singer|actor|actress|footballer|player|politician|painter|writer|born|species|genus|village|municipality|town|city|river|mountain|video game|character)\b", re.I)


def _wd_match(name: str, fetch: Callable[[str], str]) -> dict[str, Any] | None:
    """the best Wikidata search hit when it really is this company, else None"""
    res = json.loads(fetch(WD + "action=wbsearchentities&search=" + urllib.parse.quote(name) + "&language=en&format=json&limit=1"))
    hits = res.get("search") or []
    if not hits:
        return None
    hit = hits[0]
    if _NOT_A_COMPANY.search(hit.get("description") or ""):
        return None                                 # a film, song, person, place ... with the same name
    label = hit.get("label")
    if label and _norm(label) not in _norm(name) and _norm(name) not in _norm(label):
        return None                                 # a different company with a similar name: better "not found" than wrong facts
    return hit


def _wd_labels(ent: dict[str, Any], fetch: Callable[[str], str]) -> dict[str, Any]:
    """English labels of the headquarters / founder / industry items of an entity"""
    ids: list[str] = []
    for pid in ("P159", "P112", "P452"):
        ids += [v["id"] for v in _claims(ent, pid) if isinstance(v, dict) and "id" in v][:5]
    if not ids:
        return {}
    lab = json.loads(fetch(WD + "action=wbgetentities&ids=" + "|".join(dict.fromkeys(ids)) + "&props=labels&languages=en&format=json"))["entities"]
    return {k: ((v.get("labels") or {}).get("en") or {}).get("value") for k, v in lab.items()}


def _wikidata(name: str, fetch: Callable[[str], str]) -> dict[str, Any]:
    hit = _wd_match(name, fetch)
    if hit is None:
        return {}
    qid = hit["id"]
    ent = json.loads(fetch(WD + "action=wbgetentities&ids=" + qid + "&props=claims&format=json"))["entities"][qid]
    labels = _wd_labels(ent, fetch)

    def names(pid: str) -> list[Any]:
        return [labels[v["id"]] for v in _claims(ent, pid) if isinstance(v, dict) and v.get("id") in labels and labels[v["id"]]]

    emp = [v for v in _claims(ent, "P1128") if isinstance(v, dict) and "amount" in v]
    inc = [v for v in _claims(ent, "P571") if isinstance(v, dict) and "time" in v]
    return {"qid": qid, "description": hit.get("description"),
            "hq": (names("P159") or [None])[0], "founders": names("P112")[:5], "industry": (names("P452") or [None])[0],
            "employees": int(float(emp[-1]["amount"])) if emp else None,
            "founded": int(inc[0]["time"][1:5]) if inc else None}


_META = [re.compile(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]*content=["\']([^"\']+)', re.I),
         re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:name|property)=["\'](?:og:)?description["\']', re.I)]


def _site_description(url: str, fetch: Callable[[str], str]) -> str | None:
    page = fetch(url)
    for rx in _META:
        m = rx.search(page)
        if m:
            return html.unescape(m.group(1)).strip()[:400] or None
    return None


def _news(name: str, fetch: Callable[[str], str]) -> list[dict[str, Any]]:
    root = safenet.parse_xml(fetch(safenet.GOOGLE_NEWS_RSS + urllib.parse.quote('"' + name + '"') + safenet.GOOGLE_NEWS_PARAMS))
    out: list[dict[str, Any]] = []
    for it in safenet.rss_items(root):
        try:
            date = email.utils.parsedate_to_datetime(it["pubDate"]).date().isoformat()
        except (TypeError, ValueError):
            date = None
        if it["title"] and is_web_link(it["link"]):          # feed links are untrusted: http(s) only
            out.append({"title": it["title"][:200], "url": it["link"], "date": date, "source": it["source"] or "Google News"})
        if len(out) >= 5:
            break
    return out


# What parsing a web answer into the profile can raise (network, JSON/XML, missing keys, wrong shapes).
_LOOKUP_ERRORS = (*safenet.NET_ERRORS, KeyError, IndexError, TypeError, AttributeError, OverflowError)


def _save(path: str | Path, d: dict[str, Any]) -> None:
    try:
        write_atomic(path, json.dumps(d, ensure_ascii=False))
    except (OSError, TypeError, ValueError) as exc:
        safenet.swallowed("company_info._save", exc)


def _found(p: dict[str, Any]) -> None:
    g = p.get
    p["found"] = {"mission": bool(g("mission")), "hq": bool(g("hq")), "employees": g("employees") is not None,
                  "founded": g("founded") is not None, "founders": bool(g("founders")), "industry": bool(g("industry")),
                  "news": bool(g("news"))}      # .get: a cache entry written by an older version may lack keys


def _refresh_news(p: dict[str, Any], ent: dict[str, Any], name: str, fetch: Callable[[str], str], now: float) -> None:
    """cached profile whose headlines are older than NEWS_TTL: fetch the news again"""
    try:
        p["news"] = _news(name, fetch)
    except _LOOKUP_ERRORS as exc:
        safenet.swallowed("company_info.refresh_news", exc)
        p["news"] = []
    ent["news_t"] = now
    _found(p)


def _fresh_profile(name: str, web: str | None, fetch: Callable[[str], str], now: float) -> dict[str, Any]:
    """profile built from Wikidata, the company's own site and Google News"""
    p: dict[str, Any] = {"name": name, "mission": None, "hq": None, "employees": None, "founded": None, "founders": [], "industry": None,
         "news": [], "links": {"web": web, "wikidata": None}, "found": {}, "fetched_at": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(timespec="seconds")}
    wd = {}
    try:
        wd = _wikidata(name, fetch)
    except _LOOKUP_ERRORS as exc:
        safenet.swallowed("company_info.wikidata", exc)
        wd = {}
    for k in ("hq", "employees", "founded", "founders", "industry"):
        if wd.get(k) not in (None, []):
            p[k] = wd[k]
    if wd.get("qid"):
        p["links"]["wikidata"] = WIKIDATA_ENTITY + wd["qid"]
    if web:
        try:
            p["mission"] = _site_description(web, fetch)
        except _LOOKUP_ERRORS as exc:
            safenet.swallowed("company_info.company_profile", exc)
    if not p["mission"] and wd.get("description"):
        p["mission"] = wd["description"]
    try:
        p["news"] = _news(name, fetch)
    except _LOOKUP_ERRORS as exc:
        safenet.swallowed("company_info.news", exc)
        p["news"] = []
    _found(p)
    return p


def _cached_profile(ent: dict[str, Any] | None, name: str, fetch: Callable[[str], str], now: float,
                    cache: dict[str, Any], cache_path: str | Path | None) -> dict[str, Any] | None:
    """the stored profile when it is still fresh (its news are renewed when old), else None"""
    if not (ent and now - ent.get("t", 0) < FACTS_TTL and isinstance(ent.get("profile"), dict)):
        return None
    p = ent["profile"]
    if now - ent.get("news_t", 0) >= NEWS_TTL:
        _refresh_news(p, ent, name, fetch, now)
        if cache_path:
            _save(cache_path, cache)
    return p


def company_profile(name: str, web: str | None = None, fetch: Callable[[str], str] | None = None, cache_path: str | Path | None = None, now: float | None = None) -> dict[str, Any]:
    fetch = fetch or _default_fetch
    now = time.time() if now is None else now
    web = safe_web(web)
    key = _norm(name) + "|" + (web or "")
    cache = fileio.load_json_cache(cache_path, {}) if cache_path else {}
    ent = cache.get(key) if isinstance(cache.get(key), dict) else None

    p = _cached_profile(ent, name, fetch, now, cache, cache_path)
    if p is not None:
        return p

    p = _fresh_profile(name, web, fetch, now)
    if cache_path and any(p["found"].values()):          # a fully offline answer is not worth remembering
        cache[key] = {"t": now, "news_t": now, "profile": p}
        _save(cache_path, cache)
    return p

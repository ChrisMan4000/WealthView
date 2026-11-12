"""
WEALTHVIEW - online logo finder for companies that have no logo yet (used by server.py: /api/logo?name=...).

 find(name, cat, dom) -> {name, individual, dom, file, data}
   individual : the name looks like a private person -> no lookup, the dashboard shows initials
   dom        : the company's web domain (given, found through Wikidata's "official website", or guessed from the name and verified)
   data       : the logo as a data: URI (PNG/ICO) or None when nothing was found
Results (also "nothing found", for 7 days) are remembered in data/logos_online.json; images go to logos/ (only the WealthView folder is written).
Only the company NAME is sent to the public sources (Wikidata, the company's own website, icon services).
"""
from __future__ import annotations
from typing import Any
import base64
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from ...common import fileio
from ...common import paths
from ...common import safenet
from ...common.timeutil import DAY_S
from ...common.fileio import write_atomic



def logos_dir() -> Path:
    """The folder with the downloaded company logos."""
    return paths.BASE / "logos"


def _cache_file() -> Path:
    """the lookup cache; resolved when used so the data folder can be changed (tests)"""
    return paths.data_path("logos_online.json")


RETRY_DAYS = 7
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
DDG_ICON = "https://icons.duckduckgo.com/ip3/{dom}.ico"
GOOGLE_FAVICON = "https://www.google.com/s2/favicons?domain={dom}&sz=128"
SCHEMES = ("https://", "https://www.")
APPLE_TOUCH_ICON = "https://{host}/apple-touch-icon.png"
SITE_FAVICON = "https://{host}/favicon.ico"

BIZ = re.compile(r"(gmbh|\bag\b|\bkg\b|\bug\b|\bse\b|\bltd\b|\binc\b|\bllc\b|\be\.?v\.?\b|stiftung|verein|club|bank|kasse|sparkasse|versicherung|verwaltung|"
                 r"apotheke|shop|markt|energy|energie|solar|travel|group|service|partner|recht|kanzlei|praxis|studio|cafe|café|restaurant|bäckerei|"
                 r"mobile|telekom|stadtwerke|werke|verlag|schule|kita|hotel|hostel|camper|fitness|gym|bio|food|market|store|express|logistik|"
                 r"foundation|institut|gesellschaft|genossenschaft|e\.k\.|volks|kranken|hausverwaltung|steuer|beratung|agentur|media|digital|tech|cloud)", re.I)


def is_individual(name: str, cat: str = "") -> bool:
    """Private person? (e.g. 'Erika Mustermann' booked under family & private) -> initials instead of a logo."""
    n = (name or "").strip()
    if not n or BIZ.search(n) or re.search(r"\d", n):
        return False
    toks = n.split()
    if not (2 <= len(toks) <= 3) or not all(re.match(r"^[A-ZÄÖÜ][a-zäöüßéèáàç'.-]+$", t) for t in toks):
        return False
    return bool(re.search(r"famil|privat|person|friend|freund", cat or "", re.I)) or len(toks) == 2


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))


def _is_person(claims: dict[str, Any]) -> bool:
    return any((c.get("mainsnak", {}).get("datavalue", {}).get("value", {}) or {}).get("id") == "Q5" for c in claims.get("P31", []))


def _website_host(claims: dict[str, Any]) -> str | None:
    """host of the first official-website claim (P856), or None"""
    for c in claims.get("P856", []):
        u = (c.get("mainsnak", {}).get("datavalue") or {}).get("value")
        if u:
            return re.sub(r"^www\.", "", urllib.parse.urlparse(u).netloc.lower()) or None
    return None


def _wikidata_site(name: str) -> str | None:
    """official website of the best Wikidata match that is NOT a person"""
    try:
        q = urllib.parse.quote(name)
        hits = safenet.fetch_json(f"{WIKIDATA_API}?action=wbsearchentities&search={q}&language=en&uselang=en&limit=5&format=json", 8)["search"]
        if not hits:
            return None
        ids = "|".join(h["id"] for h in hits)
        ents = safenet.fetch_json(f"{WIKIDATA_API}?action=wbgetentities&ids={ids}&props=claims&format=json", 8)["entities"]
        for h in hits:
            cl = (ents.get(h["id"]) or {}).get("claims") or {}
            if _is_person(cl):
                continue
            host = _website_host(cl)
            if host is not None and safenet.safe_web("https://" + host, resolve=True) is None:
                return None                      # the host comes from Wikidata: never fetch from a private / local address
            if host is not None or any((c.get("mainsnak", {}).get("datavalue") or {}).get("value") for c in cl.get("P856", [])):
                return host
    except (*safenet.NET_ERRORS, KeyError, IndexError, TypeError, AttributeError) as exc:
        safenet.swallowed("logos_online._wikidata_site", exc)
    return None


def _alive(dom: str) -> bool:
    for sch in SCHEMES:
        try:
            req = urllib.request.Request(sch + dom, headers=safenet.DEFAULT_HEADERS)
            with safenet.urlopen(req, 5) as r:
                if r.status < 400:
                    return True
        except safenet.NET_ERRORS as exc:
            safenet.swallowed("logos_online._alive", exc)
            continue
    return False


def _guess_domain(name: str) -> str | None:
    base = _slug(name)
    words = re.sub(r"\(.*?\)", "", name).split()      # a name that is only "(...)" has no first word
    first = _slug(words[0]) if words else ""
    seen: list[str] = []
    for stem in (base, first):
        if len(stem) < 4:
            continue
        for tld in (".de", ".com", ".eu", ".net", ".org"):
            d = stem + tld
            if d not in seen:
                seen.append(d)
    for d in seen[:8]:
        if _alive(d):
            return d
    return None


def _logo_bytes(dom: str) -> bytes | None:
    for u in (APPLE_TOUCH_ICON.format(host=dom), APPLE_TOUCH_ICON.format(host="www." + dom), DDG_ICON.format(dom=dom),
              GOOGLE_FAVICON.format(dom=dom), SITE_FAVICON.format(host=dom)):
        try:
            b = safenet.fetch_bytes(u, 8)
            if len(b) > 300 and (b[:4] == b"\x89PNG" or b[:4] == b"\x00\x00\x01\x00" or b[:3] == b"\xff\xd8\xff" or b[:4] == b"GIF8"):
                return b
        except safenet.NET_ERRORS as exc:
            safenet.swallowed("logos_online._logo_bytes", exc)
            continue
    return None


def _mime(b: bytes) -> str:
    return "image/png" if b[:4] == b"\x89PNG" else "image/jpeg" if b[:3] == b"\xff\xd8\xff" else "image/gif" if b[:4] == b"GIF8" else "image/x-icon"


def _fname(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", "m:" + name) + ".png"      # same naming as logo_fetch.fetch_logos


def cached_logos() -> dict[str, Any]:
    """{'m:<name>': data URI} for every logo found so far (logo_fetch.fetch_logos merges these into src_logos.js)"""
    out = {}
    for name, e in fileio.load_json_cache(_cache_file(), {}).items():
        f = logos_dir() / (e.get("file") or "")
        if e.get("file") and f.exists():
            b = f.read_bytes()
            out["m:" + name] = f"data:{_mime(b)};base64," + base64.b64encode(b).decode()
    return out


def _data_url(b: bytes) -> str:
    return f"data:{_mime(b)};base64," + base64.b64encode(b).decode()


def _remember(name: str, dom: str | None, b: bytes | None) -> dict[str, Any]:
    """stores the logo bytes (if any) and the lookup result in the cache -> the cache entry"""
    cache = fileio.load_json_cache(_cache_file(), {})
    entry: dict[str, Any] = dict(dom=dom, file=None, t=int(time.time()))
    if b:
        try:
            logos_dir().mkdir(exist_ok=True)
            write_atomic(logos_dir() / _fname(name), b)
            entry["file"] = _fname(name)
        except OSError as exc:
            safenet.swallowed("logos_online.find", exc)
    cache[name] = entry
    try:
        write_atomic(_cache_file(), json.dumps(cache, ensure_ascii=False, indent=1))
    except (OSError, TypeError) as exc:
        safenet.swallowed("logos_online.find", exc)
    return entry


_PLAIN_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}")
_LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp")


def valid_domain(dom: object) -> bool:
    """True for a plain public host name such as 'wolt.com': no port, path, user name, IP address or local network name."""
    d = dom.strip().lower() if isinstance(dom, str) else ""
    return bool(_PLAIN_HOST.fullmatch(d)) and not d.endswith(_LOCAL_SUFFIXES)


def _from_cache(name: str, res: dict[str, Any]) -> dict[str, Any] | None:
    """the remembered answer for `name` (a stored logo, or a recent 'nothing found'), or None when we have to look it up"""
    e = fileio.load_json_cache(_cache_file(), {}).get(name)
    if e and e.get("file") and (logos_dir() / e["file"]).exists():
        return dict(res, dom=e.get("dom"), file=e["file"], data=_data_url((logos_dir() / e["file"]).read_bytes()))
    if e and not e.get("file") and time.time() - e.get("t", 0) < RETRY_DAYS * DAY_S:
        return dict(res, dom=e.get("dom"))
    return None


def remembered(name: str) -> bool:
    """True when `find(name)` would answer from its cache (a stored logo or a recent 'nothing found'): no network is needed."""
    return _from_cache((name or "").strip()[:80], {}) is not None


def find(name: str, cat: str = "", dom: str | None = None) -> dict[str, Any]:
    name = (name or "").strip()[:80]
    res: dict[str, Any] = dict(name=name, individual=False, dom=None, file=None, data=None)
    if not name:
        return res
    if is_individual(name, cat):
        res["individual"] = True
        return res
    remembered = _from_cache(name, res)
    if remembered is not None:
        return remembered
    dom = (dom.strip().lower() if isinstance(dom, str) and valid_domain(dom) and safenet.safe_web("https://" + dom.strip().lower(), resolve=True) else None) or _wikidata_site(re.sub(r"\(.*?\)", "", name).strip()) or _guess_domain(name)
    b = _logo_bytes(dom) if dom else None
    entry = _remember(name, dom, b)
    if b:
        res.update(dom=dom, file=entry["file"], data=_data_url(b))
    else:
        res["dom"] = dom
    return res


if __name__ == "__main__":
    r = find(sys.argv[1] if len(sys.argv) > 1 else "Wolt")
    r["data"] = (r["data"] or "")[:40]
    print(json.dumps(r, ensure_ascii=False))

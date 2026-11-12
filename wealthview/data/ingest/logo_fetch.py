"""WealthView - logo download: little company/coin icons -> logos/*.png -> src_logos.js.

Network use: keys with a known web domain (config logo_domains, built-in merchants) fetch that domain's icon.  For the user's OWN merchants and
positions WITHOUT a known domain (a new user has none) fetch_logos asks logos_online.find, which sends only the company / merchant / security NAME
(never amounts, IBANs, account names, dates or booking text) to Wikidata, to the company's own website and to public icon services.  find also
probes GUESSED website hosts (name + .de/.com/...): the name can therefore reach DNS and the web servers of those guessed sites.
Privacy beats coverage (fail closed): a merchant name is looked up only when ALL hold - its booking category is a commercial one (COMMERCIAL_CATS)
or the name carries a legal-form / business word; it has no special characters, digits or 'www', 3..40 chars, at most 4 words, a vowel in every word;
it is not person-shaped (stricter than logos_online.is_individual: 2-4 title-case / ALL-CAPS words, titles, particles such as van/von); and it has
no generic booking word (Lastschrift, Miete, ...).  So single-word brands booked under a non-commercial category (Family, Cash, Fees & Taxes,
Sonstiges...) are not looked up.  Position names only need to be non-empty without special characters or booking words.
Setting logo_lookup=false turns every online lookup off.  At most MAX_LOOKUPS_PER_REFRESH names per refresh; the rest follows on later refreshes
(find remembers hits and misses).  find and safenet write the network log, so nothing is logged here.
"""
from __future__ import annotations
from typing import Any
import base64, json, re
from pathlib import Path
from . import logos_online
from ...common import paths, safenet
from ...common.runcontext import RunContext
from ...common.config import setting
from ...common.fileio import write_atomic

COINCAP_ICON = "https://assets.coincap.io/assets/icons/{sym}@2x.png"
CRYPTO_ICONS_REPO = "https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/{sym}.png"


MAX_LOOKUPS_PER_REFRESH = 60       # online name lookups per refresh: a huge first history stays bounded, the rest follows next time
MAX_NAME_WORDS = 4
MAX_NAME_LEN = 40
COMMERCIAL_CATS = frozenset({"Housing & Utilities", "Home & Renovation", "Travel", "Insurance", "Groceries", "Dining & Delivery", "Transport", "Health",
                             "Subscriptions & Digital", "Shopping", "Leisure & Sport"})      # the classifier's (categories.CAT_RULES) commercial categories
_BAD_CHARS = re.compile(r"[*/+@:\\_]|www", re.I)
_BOOKING_WORDS = re.compile(r"kartenzahlung|lastschrift|gutschrift|[uü]berweisung|ueberweisung|miete|gehalt|dauerauftrag|svwz|eref|mref|kref|abschluss|"
                            r"zinsen|entgelt|geb[uü]hr|gebuehr", re.I)
_LEGAL = re.compile(r"^(gmbh|ag|kg|ug|se|ltd|inc|llc|e\.?v\.?|bank|versicherung)$", re.I)
_PARTICLES = {"van", "von", "der", "de", "zu", "ter", "bin", "al"}
_TITLES = {"dr", "dr.", "prof", "prof.", "dipl.", "ing."}
_VOWEL = re.compile(r"[aeiouyäöüéèáàíóú]", re.I)
_NAME_TOKEN = re.compile(r"^[A-ZÄÖÜ][a-zäöüßéèáàç'.]+(-[A-ZÄÖÜ][a-zäöüßéèáàç'.]+)*$|^[A-ZÄÖÜ]{2,}(-[A-ZÄÖÜ]{2,})*$")

IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF8", b"\x00\x00\x01\x00")      # PNG, JPEG, GIF, ICO


def is_image(b: bytes) -> bool:
    return b.startswith(IMAGE_MAGIC) or (b[:4] == b"RIFF" and b[8:12] == b"WEBP")


def _get_bytes(url: str, minlen: int = 300) -> bytes | None:
    """The response body when it is an image of a plausible size, else None (HTML error pages are never saved as logos)."""
    try:
        b = safenet.fetch_bytes(url, 12)
        return b if len(b) > minlen and is_image(b) else None
    except safenet.NET_ERRORS as exc:
        safenet.swallowed("logo_fetch._get_bytes", exc)
        return None


def _save_logo(folder: Path, out: dict[str, str], key: str, cands: list[str]) -> None:
    """logos/<key>.png (downloaded from the first candidate URL that answers, unless it exists) -> out[key] as a data URL"""
    f = folder / (re.sub(r"[^A-Za-z0-9_-]", "_", key) + ".png")
    if not f.exists():
        for u in cands:
            b = _get_bytes(u)
            if b:
                write_atomic(f, b)
                break
    if f.exists():
        out[key] = "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode()


def _person_shaped(toks: list[str]) -> bool:
    """Stricter than logos_online.is_individual: a title, or 2-4 words that are all title-case / ALL-CAPS names (lowercase particles between them allowed)."""
    if toks[0].lower() in _TITLES:
        return True
    if not 2 <= len(toks) <= 4 or any(_LEGAL.match(t) for t in toks):
        return False
    names = [t for t in toks if t not in _PARTICLES]
    return len(names) >= 2 and all(_NAME_TOKEN.match(t) for t in names)


def _hygienic(n: str) -> bool:
    return bool(n) and not _BAD_CHARS.search(n) and not _BOOKING_WORDS.search(n)


def _merchant_name_ok(name: str, cat: str = "") -> bool:
    """True only for a company-like merchant name that is safe to send (see the module docstring); anything doubtful is not."""
    n = (name or "").strip()
    toks = n.split()
    if not (3 <= len(n) <= MAX_NAME_LEN and 1 <= len(toks) <= MAX_NAME_WORDS) or re.search(r"\d", n) or not _hygienic(n):
        return False
    if not all(_VOWEL.search(t) or _LEGAL.match(t) for t in toks):
        return False
    if cat not in COMMERCIAL_CATS and not logos_online.BIZ.search(n):
        return False
    return not _person_shaped(toks)


def lookup_allowed(name: str, cat: str = "") -> bool:
    """May this merchant name be sent to the online logo lookup at all? logo_lookup=false says no to everything; otherwise the same fail-closed
    filter as the logo build applies (used by /api/logo, so the dashboard cannot send what the build would refuse)."""
    return bool(setting("logo_lookup", True)) and _merchant_name_ok(name, cat)


def _position_name_ok(name: str) -> bool:
    """A security name: digits are fine; empty names, special characters and booking words are not."""
    return _hygienic((name or "").strip())


def _lookup_online(out: dict[str, str], todo: list[tuple[str, str, str]], finder: Any, cap: int) -> None:
    """finder(name, cat) for up to `cap` names that need the network -> out[key] = logo data URL.  A failing finder never breaks the build."""
    used = 0
    for key, name, cat in todo:
        if key in out or logos_online.is_individual(name, cat):
            continue
        try:
            if not logos_online.remembered(name):
                if used >= cap:
                    continue
                used += 1
            r = finder(name, cat, None)
            if r and r.get("data") and not r.get("individual"):
                out[key] = r["data"]
        except Exception as exc:    # broad on purpose: the online lookup is an optional extra and must not break the logo build
            safenet.swallowed("logo_fetch._lookup_online", exc)


def fetch_logos(ctx: RunContext, positions: Any, extra: Any = None, coins: Any = (), candidates: Any = None, finder: Any = None,
                max_lookups: int = MAX_LOOKUPS_PER_REFRESH) -> None:
    """Little logo images -> logos/*.png -> src_logos.js.  keys: gls, WKN, 'm:<merchant>', 'c:<coin>'.
    candidates: (key, merchant name, category) without a known domain; positions without one are looked up by their name too (finder, default logos_online.find)."""
    d = paths.BASE / "logos"
    d.mkdir(exist_ok=True)
    dom = dict(setting("logo_domains", {}))
    dom.update(extra or {})
    keys = ["gls", "coinbase", "paypal", "worldfund", "wiwin"] + [p["wkn"] for p in positions] + list((extra or {}).keys())
    out: dict[str, str] = {}
    for k in dict.fromkeys(keys):
        if not dom.get(k):
            continue
        x = dom[k]
        _save_logo(d, out, k, [logos_online.GOOGLE_FAVICON.format(dom=x), logos_online.DDG_ICON.format(dom=x),
                               logos_online.APPLE_TOUCH_ICON.format(host=x), logos_online.SITE_FAVICON.format(host=x)])
    if setting("logo_lookup", True):
        todo = [(p["wkn"], (p.get("name") or "").strip(), "") for p in positions if not dom.get(p["wkn"]) and _position_name_ok(p.get("name") or "")]
        todo += [(k, n.strip(), c) for k, n, c in (candidates or []) if not dom.get(k) and _merchant_name_ok(n, c)]
        _lookup_online(out, todo, finder or logos_online.find, max_lookups)
    for c in coins:
        lc = c.lower()
        _save_logo(d, out, "c:" + c, [COINCAP_ICON.format(sym=lc), CRYPTO_ICONS_REPO.format(sym=lc)])
    try:                      # logos found online by the dashboard (logos_online.py) stay in
        for k, v in logos_online.cached_logos().items():
            out.setdefault(k, v)
    except Exception as exc:    # broad on purpose: the online logos are an optional extra and must not break the logo build
        safenet.swallowed("logo_fetch.fetch_logos", exc)
    write_atomic(paths.BASE / "src_logos.js", "window.SRC_LOGOS=" + json.dumps(out) + ";\n")
    ctx.set_status("logos", "ok" if out else "warn", f"{len(out)} logos")

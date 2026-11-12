"""Small shared helpers for WealthView: checked URL opening, safe XML parsing and logged best-effort errors.

Kept free of other WealthView imports so every module can use it (no import cycles).

Error contract: pure parsers and database helpers raise named exceptions (OSError, ValueError, KeyError,
json.JSONDecodeError, sqlite3.Error); the loader that calls them (loaders.py) turns them into a status line and returns None. Optional web lookups (quotes, news,
company profiles, logos) may instead return None or an empty value, but then they call swallowed(where, exc) so the
error can still be seen in the log (config.json "debug": true). A bare `except Exception` is only allowed where a
background job must not crash, and then carries a one-line comment saying so.
"""
from __future__ import annotations
from typing import Any, cast
import http.client
import ipaddress
import json
import logging
import socket
import threading
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET  # nosec B405 - input is screened by parse_xml() below

log = logging.getLogger("wealthview")

ALLOWED_SCHEMES = ("http", "https")
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q="      # + the quoted search text + GOOGLE_NEWS_PARAMS
GOOGLE_NEWS_PARAMS = "&hl=en-US&gl=US&ceid=US:en"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/xml,*/*",
}
MAX_BYTES = 3_000_000
# Everything a fetch/parse of a web answer can raise: URLError/HTTPError/timeouts (OSError), bad JSON/XML/text
# (ValueError, incl. json.JSONDecodeError and UnicodeError), malformed XML (ET.ParseError) and protocol errors (http.client.HTTPException).
NET_ERRORS = (OSError, ValueError, http.client.HTTPException, ET.ParseError)


def check_url(target: str | urllib.request.Request) -> str:
    """Return the URL string of a str or urllib Request; raise ValueError unless it is http(s)."""
    url = target if isinstance(target, str) else target.full_url
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"URL scheme not allowed: {scheme!r}")
    return url


def urlopen(target: str | urllib.request.Request, timeout: float) -> http.client.HTTPResponse:
    """urllib.request.urlopen that only accepts http(s) URLs (no file:, ftp:, custom schemes)."""
    check_url(target)
    return cast(http.client.HTTPResponse, urllib.request.urlopen(target, timeout=timeout))  # nosec B310 - scheme checked above


def open_with(opener: urllib.request.OpenerDirector, request: urllib.request.Request, timeout: float) -> http.client.HTTPResponse:
    """opener.open() with the same http(s)-only rule as urlopen()."""
    check_url(request)
    return cast(http.client.HTTPResponse, opener.open(request, timeout=timeout))  # nosec B310 - scheme checked above


def fetch_bytes(url: str, timeout: int = 12, opener: urllib.request.OpenerDirector | None = None,
                headers: dict[str, str] | None = None, max_bytes: int = MAX_BYTES) -> bytes:
    """GET `url` (http/https only) and return at most `max_bytes` bytes. Raises on network or HTTP errors."""
    req = urllib.request.Request(url, headers=headers or DEFAULT_HEADERS)
    with (open_with(opener, req, timeout) if opener else urlopen(req, timeout)) as r:
        return r.read(max_bytes)


def fetch_text(url: str, timeout: int = 12, opener: urllib.request.OpenerDirector | None = None, headers: dict[str, str] | None = None) -> str:
    """GET `url` and return the body as text (UTF-8, undecodable bytes replaced)."""
    return fetch_bytes(url, timeout, opener, headers).decode("utf-8", "replace")


def fetch_json(url: str, timeout: int = 12, opener: urllib.request.OpenerDirector | None = None, headers: dict[str, str] | None = None) -> Any:
    """GET `url` and parse the body as JSON."""
    return json.loads(fetch_text(url, timeout, opener, headers))


def rss_items(root: ET.Element) -> list[dict[str, Any]]:
    """The <item>s of a parsed RSS feed as dicts: title (a trailing ' - source' removed), source ('' if missing), link and pubDate (None if missing)."""
    out: list[dict[str, Any]] = []
    for it in root.iter("item"):
        title, src = (it.findtext("title") or "").strip(), (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        out.append(dict(title=title, source=src, link=it.findtext("link"), pubDate=it.findtext("pubDate")))
    return out


def parse_xml(data: bytes | str) -> ET.Element:
    """Parse an XML document from the web (RSS). Documents with a DTD or entity declarations are refused,
    which closes the entity-expansion ("billion laughs") hole of the standard-library parser."""
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    head = raw.upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise ValueError("XML with DTD or entity declarations refused")
    return ET.fromstring(raw)  # nosec B314 - DTD/entities refused above


# Host names that only exist inside a home / company network.
_PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")


def is_web_link(url: Any) -> bool:
    """True for an http(s) address with a host - the only kind of link that may be shown or opened (no javascript:, file: ...)."""
    try:
        u = urllib.parse.urlparse(str(url or "").strip())
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.netloc)


def is_public_host(host: str | None, resolve: bool = False) -> bool:
    """False for localhost, private / loopback / link-local addresses and local-network names. With resolve=True the name is
    also looked up in DNS and every address it points to must be public."""
    host = (host or "").strip("[]").rstrip(".").lower()
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_global          # a literal IP address
    except ValueError:
        pass                                                  # not an IP: a normal host name
    if "." not in host or host.endswith(_PRIVATE_SUFFIXES):
        return False
    if resolve:
        try:
            found = socket.getaddrinfo(host, None)
            return bool(found) and all(ipaddress.ip_address(str(f[4][0]).split("%")[0]).is_global for f in found)
        except (OSError, ValueError):
            return False
    return True


def safe_web(url: str | None, resolve: bool = False) -> str | None:
    """Only plain http(s) addresses of PUBLIC hosts may be fetched (the address comes from the page): no file:, localhost,
    private / link-local IPs or local names, and no unusual ports."""
    try:
        u = urllib.parse.urlparse(str(url or "").strip())
        port = u.port
    except ValueError:
        return None
    if not is_web_link(u.geturl()) or port not in (None, 80, 443) or not is_public_host(u.hostname, resolve):
        return None
    return u.geturl()


def configure_logging(debug: bool = False) -> None:
    """Send log messages to stderr, once per program start (bootstrap.bootstrap calls it for the server and for refresh.py).
    Warnings are always shown; with "debug": true in config.json the ignored errors of swallowed() show up too."""
    logging.basicConfig(level=logging.DEBUG if debug else logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(logging.DEBUG if debug else logging.WARNING)      # basicConfig does nothing when handlers already exist
    with _WARNED_LOCK:
        _WARNED.clear()         # a new run: every label may warn once again


_WARNED: set[str] = set()      # labels swallowed() has already warned about in this run
_WARNED_LOCK = threading.Lock()


def swallowed(where: str, exc: BaseException, *, routine: bool = False) -> None:
    """Record a deliberately ignored error (best-effort step). The first one per `where` label in a run is logged as a WARNING, so a
    broken optional step does not stay invisible; repeats (and `routine` ones, an expected miss like a setting that is not in
    config.json) go to the debug log with the full detail ("debug": true in config.json shows them)."""
    with _WARNED_LOCK:
        first = where not in _WARNED and not routine
        if first:
            _WARNED.add(where)
    if first:
        log.warning("ignored error in %s: %s: %s (more of these only at debug level)", where, type(exc).__name__, exc)
    else:
        log.debug("ignored error in %s: %s: %s", where, type(exc).__name__, exc, exc_info=exc)
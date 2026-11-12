"""
WEALTHVIEW - network connection log for the world-map box.

Only connections started BY WEALTHVIEW are recorded (server.py, refresh.py, research.py, logos_online.py, the Coinbase call).
Nothing else on the PC is looked at - this is not a system-wide monitor.

 install()          call once at start-up: every urllib request made by this program is written to netlog.jsonl (host + time only,
                    never the full address, never prices, names or numbers)
 uninstall()        undo install() (the tests use it so they leave urllib as they found it)
 log(host, label)   record one connection by hand (used for the Coinbase helper, which runs outside Python)
 snapshot()         for /api/netlog: {home, nodes:[{host,label,city,country,lat,lon,n,last,ok}], total, countries}

Where a host is: (1) netgeo.json cache, (2) the offline DB-IP file if the 'maxminddb' package and a dbip.mmdb file exist
(config "geo_db", or ~/OpenJarvis/tools/dbip.mmdb, opened read-only), (3) ip-api.com (only the server's IP address is sent),
(4) a small built-in table for the usual services. Only netlog.jsonl and netgeo.json are written.
"""
from __future__ import annotations
from typing import Any
import json
import socket
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from . import config
from . import fileio
from . import paths
from . import safenet
from .timeutil import DAY_S, HOUR_S
from .fileio import write_atomic
from .types.network import GeoHit, NetlogSnapshot

WINDOW = 3 * HOUR_S            # connections of the last 3 hours are shown
MAXBYTES = 600_000
_lock = threading.Lock()


def _log_file() -> Path:
    """the connection log; resolved when used so the data folder can be changed (tests)"""
    return paths.data_path("netlog.jsonl")
_tl = threading.local()


class _State:
    """process-wide netlog state: whether urllib is patched, and the lazily opened GeoIP database"""
    installed = False
    original: Any = None        # urllib's own OpenerDirector.open, kept so uninstall() can put it back
    geo_db: Any = None
    geo_tried = False


_state = _State()
IP_API = "http://ip-api.com/json/{ip}?fields=status,country,city,lat,lon"   # free tier is http-only
_KEEP_LINES = 1500            # log lines kept when the file is trimmed (and read for the snapshot)
_GEO_TTL = 30 * DAY_S         # seconds a located host stays cached

LABELS = (("yahoo.com", "Yahoo Finance"), ("news.google.com", "Google News"), ("google.com", "Google"), ("wikidata.org", "Wikidata"),
          ("coinbase.com", "Coinbase"), ("anthropic.com", "Claude API"), ("duckduckgo.com", "Icon service"), ("ip-api.com", "Geo lookup"),
          ("open-meteo.com", "Weather"))
# last-resort positions of the usual services (city of the provider's main data centre) when no lookup is possible
FALLBACK = {"yahoo.com": ("Sunnyvale", "United States", 37.37, -122.04), "google.com": ("Mountain View", "United States", 37.42, -122.08),
            "wikidata.org": ("Ashburn", "United States", 39.04, -77.49), "coinbase.com": ("San Francisco", "United States", 37.77, -122.42),
            "anthropic.com": ("San Francisco", "United States", 37.77, -122.42), "duckduckgo.com": ("Paris", "France", 48.86, 2.35)}


def _home() -> dict[str, Any]:
    try:
        c = config.load_config().get("home") or {}
        return dict(name=str(c.get("name", "Home")), lat=float(c.get("lat", 51.0)), lon=float(c.get("lon", 10.0)))
    except (OSError, ValueError, TypeError, AttributeError):
        return dict(name="Home", lat=51.0, lon=10.0)


def _label(host: str) -> str:
    for suf, lab in LABELS:
        if host == suf or host.endswith("." + suf):
            return lab
    return host


def log(host: str, label: str | None = None, ok: bool = True, err: bool = False) -> None:
    """append one line; never raises"""
    try:
        host = (host or "").lower()
        if not safenet.is_public_host(host) or getattr(_tl, "quiet", False):
            return
        line = json.dumps(dict(t=round(time.time(), 1), h=host, l=label or _label(host), ok=1 if ok else 0, e=1 if err else 0), ensure_ascii=False)
        with _lock:
            log_file = _log_file()
            if log_file.exists() and log_file.stat().st_size > MAXBYTES:
                keep = log_file.read_text("utf-8", "replace").splitlines()[-_KEEP_LINES:]
                write_atomic(log_file, "\n".join(keep) + "\n")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except (OSError, ValueError) as exc:
        safenet.swallowed("netlog.log", exc)


def install() -> None:
    """make every urllib request of this process show up in the log (only host + time)"""
    if _state.installed:
        return
    _state.installed = True
    orig = _state.original = urllib.request.OpenerDirector.open

    def patched(self: Any, fullurl: Any, data: Any = None, timeout: Any = socket._GLOBAL_DEFAULT_TIMEOUT) -> Any:  # type: ignore[attr-defined]  # private default sentinel of the stdlib
        try:
            u = fullurl.full_url if hasattr(fullurl, "full_url") else str(fullurl)
            host = urllib.parse.urlparse(u).hostname or ""
        except (ValueError, AttributeError):
            host = ""
        log(host)                               # recorded the moment the connection starts (the map reacts at once)
        try:
            return orig(self, fullurl, data, timeout)
        except Exception:      # broad on purpose: any failure is re-raised below, this only marks the node red
            log(host, ok=False, err=True)       # failure marker: turns the node red, is not counted as another call
            raise
    urllib.request.OpenerDirector.open = patched  # type: ignore[method-assign]  # the whole point: log every outbound request


def uninstall() -> None:
    """put urllib back the way it was before install(); does nothing when install() was not called"""
    if _state.installed and _state.original is not None:
        setattr(urllib.request.OpenerDirector, "open", _state.original)
    _state.installed = False
    _state.original = None


# ------------------------------------------------------------------ where is a host
def _jload(p: str | Path) -> dict[str, Any]:
    return fileio.load_json_cache(p, {})


def _mmdb() -> Any:
    if not _state.geo_tried:
        _state.geo_tried = True
        try:
            import maxminddb   # optional dependency: imported lazily so the app runs without it
            try:
                path = config.load_config().get("geo_db")
            except (OSError, ValueError, AttributeError):
                path = None
            for c in ([Path(path)] if path else []) + [Path.home() / "OpenJarvis" / "tools" / "dbip.mmdb"]:
                if c.exists():
                    _state.geo_db = maxminddb.open_database(str(c))
                    break
        except (ImportError, OSError, ValueError, RuntimeError):
            _state.geo_db = None
    return _state.geo_db


def _via_db(ip: str) -> GeoHit | None:
    db = _mmdb()
    if not db:
        return None
    try:
        r = db.get(ip) or {}
        loc = r.get("location") or {}
        if loc.get("latitude") is None:
            return None
        nm = lambda k: ((r.get(k) or {}).get("names") or {}).get("en", "")
        return GeoHit(city=nm("city"), country=nm("country"), lat=loc["latitude"], lon=loc["longitude"], src="dbip")
    except (KeyError, TypeError, ValueError, AttributeError, OSError, RuntimeError):
        return None


def _via_web(ip: str) -> GeoHit | None:
    _tl.quiet = True
    try:
        req = urllib.request.Request(IP_API.format(ip=ip),
                                     headers={"User-Agent": "WealthView/1.0"})
        j = json.loads(safenet.urlopen(req, 5).read().decode("utf-8", "replace"))
        if j.get("status") == "success":
            return GeoHit(city=j.get("city", ""), country=j.get("country", ""), lat=j["lat"], lon=j["lon"], src="ip-api")
    except safenet.NET_ERRORS + (KeyError, TypeError) as exc:
        safenet.swallowed("netlog._via_web", exc)
    finally:
        _tl.quiet = False
    return None


def locate(host: str, cache: dict[str, Any]) -> GeoHit | None:
    e = cache.get(host)
    if e and time.time() - e.get("t", 0) < _GEO_TTL and e.get("lat") is not None:
        return e
    res = None
    ip = None
    try:
        ip = socket.gethostbyname(host)
        res = _via_db(ip) or _via_web(ip)
    except safenet.NET_ERRORS as exc:
        safenet.swallowed("netlog.locate", exc)
    if not res:
        for suf, (city, ctry, la, lo) in FALLBACK.items():
            if host == suf or host.endswith("." + suf):
                res = dict(city=city, country=ctry, lat=la, lon=lo, src="table")
                break
    if not res:
        return e or None
    res["ip"], res["t"] = ip, int(time.time())
    cache[host] = res
    return res


def sig() -> str:
    """changes whenever any WealthView process writes a new log line"""
    try:
        s = _log_file().stat()
        return f"{s.st_mtime_ns}-{s.st_size}"
    except OSError:
        return "0"


def wait(old: str, timeout: float = 25.0) -> None:
    """block (cheaply: one file stat every 0.3 s) until the log changes or the time is up"""
    end = time.time() + timeout
    while time.time() < end and sig() == old:
        time.sleep(0.3)


def _recent_rows(now: float) -> list[dict[str, Any]]:
    """log lines of the last WINDOW seconds"""
    rows = []
    try:
        for ln in _log_file().read_text("utf-8", "replace").splitlines()[-_KEEP_LINES:]:
            try:
                r = json.loads(ln)
                if now - r["t"] <= WINDOW:
                    rows.append(r)
            except (ValueError, KeyError, TypeError) as exc:
                safenet.swallowed("netlog.snapshot", exc)
    except (OSError, ValueError) as exc:
        safenet.swallowed("netlog.snapshot", exc)
    return rows


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """log lines -> one entry per host: label, call count, last call time, ok flag"""
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        a = agg.setdefault(r["h"], dict(host=r["h"], label=r.get("l") or r["h"], n=0, last=0, ok=1))
        if r.get("e"):
            a["ok"] = 0
            continue
        a["n"] += 1
        a["last"] = max(a["last"], r["t"])
        a["ok"] = 1
    return agg


def snapshot() -> NetlogSnapshot:
    now = time.time()
    rows = _recent_rows(now)
    agg = _aggregate(rows)
    geo_file = paths.data_path("netgeo.json")
    cache = _jload(geo_file)
    before = json.dumps(cache, sort_keys=True)
    nodes = []
    for a in sorted(agg.values(), key=lambda x: -x["last"])[:40]:
        g = locate(a["host"], cache)
        if g:
            nodes.append(dict(a, city=g.get("city", ""), country=g.get("country", ""), lat=g["lat"], lon=g["lon"], src=g.get("src", "")))
    if json.dumps(cache, sort_keys=True) != before:
        try:
            write_atomic(geo_file, json.dumps(cache, ensure_ascii=False, indent=1))
        except OSError as exc:
            safenet.swallowed("netlog.snapshot", exc)
    return dict(sig=sig(), home=_home(), nodes=nodes, total=len(rows), hosts=len(agg), countries=len({n["country"] for n in nodes if n["country"]}),
                since=min([r["t"] for r in rows], default=None), now=now)


if __name__ == "__main__":
    install()
    print(json.dumps(snapshot(), indent=1))

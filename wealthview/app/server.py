"""
WEALTHVIEW local server - version in version.js  (127.0.0.1 only - nothing here is reachable from other computers).

The full route list with the auth of each route is in ARCHITECTURE.md, section 4 (Server endpoints).
Short version: the dashboard files and /api/ping, /api/hb, /api/bye, /api/unlock are public; every other /api/ route needs the
session token from /api/unlock (deny by default, see PUBLIC_API). This module is routing and handlers only; sign-in is in auth.py,
the browser-tab lifetime in lifetime.py and the refresh subprocess / folder watcher in jobs.py.
"""
from __future__ import annotations
from typing import Any, Callable, TypeVar
from typing import ParamSpec
import contextlib, functools, json, shutil, sys, threading, time
import datetime as dt
from pathlib import Path
import sqlite3
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..analysis import advisor, ask, research
from ..common import audit, config, netlog, paths, safenet
from ..common.bootstrap import bootstrap
from ..common.profile import load_profile
from ..data.finance import catrules
from ..data.ingest import company_info, db_queries, db_rules, db_schema, logo_fetch, logos_online, quotes
from . import auth, jobs, lifetime

LIVE_TTL_S = 20            # live quotes are re-fetched at most this often
NETLOG_WAIT_S = 25         # longest long-poll wait of /api/netlog
MAX_BODY = 2_000_000      # largest accepted request body in bytes
READ_AUDIT_EVERY_S = 600  # the audit log notes a read of the full data set at most this often (the page re-reads it every update)


class LiveQuotes:
    """the last live-quote answer and when it was fetched"""

    def __init__(self) -> None:
        self.t = 0.0
        self.v: dict[str, Any] = {}
        self.lock = threading.Lock()        # one quote fetch at a time

    def reset(self) -> None:
        """Forget the answer (a refresh just changed the data)."""
        self.t = 0


class ServerState:
    """Everything the server changes while it runs, in one place (the handlers reach it as STATE)."""

    def __init__(self) -> None:
        self.auth = auth.AuthState()
        self.life = lifetime.PageLife()
        self.live = LiveQuotes()
        self.refresher = jobs.Refresher(on_finished=self.live.reset)
        self.last_read_audit = 0.0         # time of the last 'read_data' audit entry


STATE = ServerState()
STATIC = {"/": "wealthview.html", "/wealthview.html": "wealthview.html", "/wf_logos.js": "wf_logos.js",
          "/wv.js": "wv.js", "/layout.js": "layout.js", "/flowpop.js": "flowpop.js", "/catrules.js": "catrules.js", "/analytics.js": "analytics.js", "/insights.js": "insights.js", "/wv_demo.js": "wv_demo.js", "/wf_data.js": "wf_data.js", "/wv-intro.js": "wv-intro.js", "/version.js": "version.js", "/land-110m.json": "vendor/land-110m.json", "/favicon.ico": "icons/wealthview.ico"}
# Deny by default: every /api/ route needs a PIN session unless it is listed here, so a new route is protected without anyone
# having to remember to lock it. Static files are public except the ones in LOCKED_PATHS (answered as an empty script).
PUBLIC_API = frozenset({"/api/ping", "/api/hb", "/api/bye", "/api/unlock"})
LOCKED_PATHS = frozenset({"/wf_data.js"})
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".ico": "image/x-icon", ".png": "image/png", ".json": "application/json"}

P = ParamSpec("P")
T = TypeVar("T")


def api_boundary(**extra: Any) -> Callable[[Callable[P, T]], Callable[P, T | dict[str, Any]]]:
    """HTTP boundary for the JSON handlers: any failure becomes {"ok": False, "error": ..., **extra} for the page (one error shape for
    all of them) instead of killing the request thread. A dict answer without an "ok" key gets one: True, or False when it carries an "error".
    (Two answers are plain documents, not envelopes: /api/real = data.json and /api/src_logos = the logo map; their failures use the error shape.)"""
    def wrap(fn: Callable[P, T]) -> Callable[P, T | dict[str, Any]]:
        @functools.wraps(fn)        # keeps the name and docstring of the wrapped handler
        def inner(*args: P.args, **kwargs: P.kwargs) -> T | dict[str, Any]:
            try:
                result = fn(*args, **kwargs)
            except Exception as e:      # broad on purpose: HTTP boundary - any failure is reported to the page, the handler must not die
                return {"ok": False, "error": str(e), **extra}
            if isinstance(result, dict) and "ok" not in result:
                return {"ok": not result.get("error"), **result}
            return result
        return inner
    return wrap


def lookup_route(event: str, **extra: Any) -> Callable[[Callable[P, T]], Callable[P, T | dict[str, Any]]]:
    """api_boundary plus one audit entry per call: the event name only, never the query text."""
    def wrap(fn: Callable[P, T]) -> Callable[P, T | dict[str, Any]]:
        @functools.wraps(fn)
        def audited(*args: P.args, **kwargs: P.kwargs) -> T:
            audit.record(event)
            return fn(*args, **kwargs)
        return api_boundary(**extra)(audited)
    return wrap


@api_boundary()
def unlock_reply(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """(HTTP code, reply) of /api/unlock; an unexpected failure (e.g. an invalid config.json) becomes {ok: false, error} via the boundary."""
    return STATE.auth.unlock(body.get("pin", ""))


@api_boundary()
def lock_reply(token: str) -> dict[str, Any]:
    """Sign the token out and answer {ok: true}; a failure becomes {ok: false, error}."""
    STATE.auth.sign_out(token)
    audit.record("lock")
    return {"ok": True}


def param(q: dict[str, list[str]], name: str, limit: int = 80) -> str:
    """One query-string value, cut to `limit` characters ('' when missing)."""
    return (q.get(name) or [""])[0][:limit]


def http_news_only(result: Any) -> Any:
    """A research answer whose news items keep only http(s) links (a feed could contain a javascript: link)."""
    if isinstance(result, dict) and isinstance(result.get("news"), list):
        news = [n for n in result["news"] if isinstance(n, dict) and (n.get("demo") or company_info.is_web_link(n.get("url")))]
        return {**result, "news": news}
    return result


def open_data_db() -> contextlib.closing[sqlite3.Connection]:
    """A database connection that closes itself: `with open_data_db() as conn:` (sqlite3's own `with` does not close)."""
    return contextlib.closing(db_schema.connect(paths.data_path(db_schema.DB_NAME)))


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "WealthView"

    def log_message(self, *a: Any) -> None:
        pass

    # ---------------------------------------------------------- helpers
    def _send(self, code: int, body: Any, ctype: str = "application/json", extra: dict[str, str] | None = None) -> None:
        if code >= 400 and isinstance(body, dict):
            body = {"ok": False, **body}        # every error answer carries ok:false next to its "error" text
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        h = (self.headers.get("Host") or "").split(":")[0]
        if h not in ("127.0.0.1", "localhost"):
            return False
        o = self.headers.get("Origin")
        return not o or o.split("//")[-1].split(":")[0] in ("127.0.0.1", "localhost")

    def _authed(self) -> bool:
        return STATE.auth.is_signed_in(self.headers.get("X-WV-Token", ""))

    def _blocked(self, path: str) -> bool:
        """Central PIN gate: True (and the reply already sent) when `path` needs a session and there is none."""
        needs_pin = path in LOCKED_PATHS or (path.startswith("/api/") and path not in PUBLIC_API)
        if not needs_pin or self._authed():
            return False
        if path.endswith(".js"):
            self._send(200, "", MIME[".js"])
        else:
            self._send(401, {"error": "locked"})
        return True

    def _json(self) -> dict[str, Any]:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 <= n <= MAX_BODY:
                return {}
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError):      # bad length, unreadable or not JSON -> treated as an empty body
            return {}
        return body if isinstance(body, dict) else {}      # every handler expects an object

    # -------------------------------------------------------------- GET
    def _query(self) -> dict[str, list[str]]:
        return urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")

    @lookup_route("lookup_logo")
    def _api_logo(self) -> Any:
        # looks up a missing company logo online (only the company name leaves this PC) -> needs the PIN session
        q = self._query()
        name, cat = param(q, "name"), param(q, "cat")
        if not logo_fetch.lookup_allowed(name, cat):       # logo_lookup=false, or a name the build would not send either: nothing leaves the PC
            return dict(name=(name or "").strip()[:80], individual=False, dom=None, file=None, data=None)
        return logos_online.find(name, cat, param(q, "dom") or None)

    @lookup_route("lookup_company")
    def _api_company(self) -> Any:
        # public facts about ONE company (Wikidata, its own site, Google News) fetched when you click it -> needs the PIN session
        q = self._query()
        web = param(q, "web", 200)
        if web and safenet.safe_web(web, resolve=True) is None:      # only public http(s) sites: never file:, localhost or a LAN address
            return {"ok": False, "error": "web address not allowed"}
        return company_info.company_profile(param(q, "name", 120), web or None, cache_path=str(paths.data_path("company_cache.json")))

    @lookup_route("lookup_research")
    def _api_research(self) -> Any:
        # public market information about ONE security fetched when you click a position; the request itself reveals
        # which security you hold, so it needs the PIN session like /api/logo and /api/company
        q = self._query()
        return http_news_only(research.research(param(q, "sym"), param(q, "name"), param(q, "wkn")))

    def _api_src_logos(self) -> Any:
        # logos generated from your own merchants, positions and coins -> needs the PIN session (the file is never served directly)
        # success = the logo map itself (wv.js uses it as it is); failure = the usual {ok: False, error} (wv.js skips an answer with "error")
        try:
            text = (paths.BASE / "src_logos.js").read_text("utf-8")
            return json.loads(text[text.index("=") + 1:].strip().rstrip(";"))
        except (OSError, ValueError) as exc:
            safenet.swallowed("server.src_logos", exc)
            return {"ok": False, "error": "no generated logos yet"}

    @api_boundary()
    def _api_profile(self) -> Any:
        # what this installation shows (layout.js decides the boxes from it); the source folders stay on the server
        p = load_profile().to_dict()
        p["sources"] = [{"kind": s["kind"], "entity": s["entity"]} for s in p["sources"]]
        return p

    @api_boundary(nodes=[])
    def _api_netlog(self) -> Any:
        q = self._query()
        old = (q.get("sig") or [""])[0]
        if (q.get("wait") or [""])[0] == "1" and old and old == netlog.sig():
            netlog.wait(old, NETLOG_WAIT_S)          # long poll: answers as soon as a new connection is logged
        return netlog.snapshot()

    def _api_real(self) -> None:
        f = paths.data_path("data.json")
        if not f.exists():
            return self._send(404, {"error": "no data yet - press REFRESH"})
        now = time.time()
        if now - STATE.last_read_audit >= READ_AUDIT_EVERY_S:      # the page re-reads the data often: note it only now and then
            STATE.last_read_audit = now
            audit.record("read_data")
        return self._send(200, f.read_bytes())

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?")[0]
        if self._blocked(path):
            return
        if path in STATIC:
            return self._static(STATIC[path])
        if path == "/api/real":
            return self._api_real()
        handlers = {"/api/hb": self._api_hb, "/api/ping": self._api_ping, "/api/live": self._live,
                    "/api/logo": self._api_logo, "/api/company": self._api_company, "/api/research": self._api_research,
                    "/api/netlog": self._api_netlog, "/api/profile": self._api_profile, "/api/src_logos": self._api_src_logos,
                    "/api/ask/status": self._api_ask_status, "/api/unusual_seen": self._api_seen_get,
                    "/api/cat/overview": self._api_cat_overview}
        if path in handlers:
            return self._send(200, handlers[path]())
        self._send(404, {"error": "not found"})

    def _static(self, name: str) -> None:
        """send one of the page files (STATIC maps the URL to the file name)"""
        f = paths.BASE / name
        if f.exists():
            return self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
        # a missing file is a 404 (never an empty 200): optional scripts carry an onerror handler in wealthview.html
        return self._send(404, {"error": "missing " + name})

    def _api_hb(self) -> dict[str, Any]:
        STATE.life.heartbeat((self._query().get("id") or ["?"])[0][:40])
        return {"ok": True}

    def _api_ping(self) -> dict[str, Any]:
        return {"ok": True, "app": "WealthView", "version": paths.version()}

    @api_boundary()
    def _api_ask_status(self) -> dict[str, Any]:
        return ask.lm_status(config.load_config().get("ask", {}))

    def _live(self) -> dict[str, Any]:
        live = STATE.live
        with live.lock:
            if time.time() - live.t < LIVE_TTL_S and live.v:
                return live.v
            try:
                data = json.loads((paths.data_path("data.json")).read_text("utf-8"))
                prices = quotes.live_prices(data)
                live.t, live.v = time.time(), dict(ok=True, t=dt.datetime.now().isoformat(timespec="seconds"), prices=prices)
            except Exception as e:      # broad on purpose: HTTP boundary - any failure is reported to the page, the handler must not die
                live.t, live.v = time.time(), dict(ok=False, t=None, prices={}, error=str(e))
            return live.v

    # ------------------------------------------------------------- POST
    def _unlock(self, body: dict[str, Any]) -> None:
        out = unlock_reply(body)
        if isinstance(out, tuple):
            return self._send(*out)
        return self._send(200, out)      # the boundary caught an error: {ok: false, error}

    @api_boundary()
    def _ask_reply(self, q: str, body: dict[str, Any]) -> dict[str, Any]:
        if not q:
            return {"ok": False, "error": "empty question"}
        if not (paths.data_path(db_schema.DB_NAME)).exists():
            return {"ok": False, "error": "The database does not exist yet - press Refresh data once."}
        try:
            portfolio = advisor.portfolio_summary(json.loads(paths.data_path("data.json").read_text("utf-8")))
        except (OSError, ValueError):
            portfolio = ""
        return dict(ask.answer(paths.data_path(db_schema.DB_NAME), q, body.get("history"), config.load_config().get("ask", {}), portfolio=portfolio))

    def _ask(self, body: dict[str, Any]) -> None:
        q = str(body.get("question") or "").strip()
        audit.record("ask", f"{len(q)} characters")
        return self._send(200, self._ask_reply(q, body))

    def _lock(self) -> None:
        return self._send(200, lock_reply(self.headers.get("X-WV-Token", "")))

    def do_POST(self) -> None:
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?")[0]
        if self._blocked(path):
            return
        if path == "/api/bye":            # the page was closed (sendBeacon): the server may stop after a short grace
            STATE.life.goodbye((self._query().get("id") or ["?"])[0][:40])
            return self._send(200, {"ok": True})
        body = self._json()
        if path == "/api/unlock":
            return self._unlock(body)
        if path == "/api/lock":           # sign out: the session token stops working at once
            return self._lock()
        if path == "/api/refresh":
            return self._send(200, self._refresh())
        if path == "/api/quick":
            return self._send(200, self._refresh(["--quick"], jobs.QUICK_REFRESH_TIMEOUT_S))
        if path == "/api/unusual_seen":
            keys = body.get("keys")
            return self._send(200, self._api_seen_add(keys if isinstance(keys, list) else []))
        if path == "/api/ask":
            return self._ask(body)
        if path == "/api/cat/set":
            return self._send(200, self._api_cat_set(body))
        if path == "/api/cat/delete":
            return self._send(200, self._api_cat_delete(body))
        self._send(404, {"error": "not found"})

    @api_boundary()
    def _api_cat_overview(self) -> dict[str, Any]:
        """Merchants with their category and a few bookings each, for the category-correction pop-up (?only=sonstiges|all&q=)."""
        q = self._query()
        only = "all" if param(q, "only") == "all" else "sonstiges"
        with open_data_db() as conn:
            return catrules.overview(conn, only, param(q, "q", 60))

    @api_boundary()
    def _api_cat_set(self, body: dict[str, Any]) -> dict[str, Any]:
        """Saves one correction: scope 'merchant' (a rule for every booking of that merchant), 'text' (a keyword rule) or 'booking' (one booking only)."""
        scope, cat = str(body.get("scope") or "merchant"), body.get("category")
        audit.record("category_set", scope)
        with open_data_db() as conn:
            if scope == "booking":
                db_rules.set_override(conn, body.get("key"), cat, body.get("name"))
            else:
                db_rules.add_rule(conn, "text" if scope == "text" else "merchant", body.get("name"), cat)
        return {"saved": True}

    @api_boundary()
    def _api_cat_delete(self, body: dict[str, Any]) -> dict[str, Any]:
        """Removes a saved rule (id) or a single-booking correction (key)."""
        audit.record("category_delete")
        with open_data_db() as conn:
            if body.get("key"):
                db_rules.delete_override(conn, body.get("key"))
            else:
                db_rules.delete_rule(conn, body.get("id"))
        return {"deleted": True}

    @api_boundary(seen=[])
    def _api_seen_get(self) -> dict[str, Any]:
        """The server-side list of dismissed 'Unusual bookings' keys."""
        with open_data_db() as conn:
            return {"seen": db_queries.unusual_seen_get(conn)}

    @api_boundary(seen=[])
    def _api_seen_add(self, keys: list[Any]) -> dict[str, Any]:
        """Adds keys to the dismissed list and returns the new list."""
        with open_data_db() as conn:
            return {"seen": db_queries.unusual_seen_add(conn, keys)}

    def _refresh(self, args: list[str] | None = None, tmo: int = jobs.FULL_REFRESH_TIMEOUT_S) -> dict[str, Any]:
        audit.record("refresh_quick" if args else "refresh_full")
        return STATE.refresher.run(args, tmo)

def runtime_check() -> None:
    """Log a clear message when the runtime baseline (Python 3.10+, Node.js for Coinbase) is not met."""
    if sys.version_info < (3, 10):
        safenet.log.error("WealthView needs Python 3.10 or newer, found %s", sys.version.split()[0])
    if not shutil.which("node") and not Path(r"C:\Program Files\nodejs\node.exe").exists():
        safenet.log.warning("Node.js was not found: the Coinbase balances cannot be refreshed (install Node.js 18 or newer)")


def main() -> None:
    if "--set-pin" in sys.argv[1:]:
        sys.exit(auth.set_pin())
    cfg = config.load_config()
    bootstrap()
    print("WealthView", paths.version(), flush=True)
    problem = auth.pin_setup_error(cfg)
    if problem:
        safenet.log.error("PIN problem: %s", problem)
    runtime_check()
    port = int(cfg.get("port", 8780))
    srv = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    print(f"WealthView on http://127.0.0.1:{port}/")
    if cfg.get("auto_stop", True):
        threading.Thread(target=lifetime.watchdog, args=(STATE.life,), daemon=True).start()
    if cfg.get("auto_import", True):
        threading.Thread(target=jobs.folder_watcher, args=(STATE.refresher, int(cfg.get("watch_seconds", 60))), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt as exc:      # Ctrl+C is the normal way to stop the server
        safenet.swallowed("server.main", exc)


if __name__ == "__main__":
    main()

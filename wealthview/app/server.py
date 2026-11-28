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
from ..common import audit, config, folderbrowse, netlog, paths, safenet
from ..common.bootstrap import bootstrap
from ..common.profile import load_profile
from ..data.finance import catrules, groceries
from ..data.ingest import company_info, db_queries, db_rules, db_schema, db_setup, exchanges, logo_fetch, logos_online, quotes, watchlist
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
        self.read_audit: dict[str, float] = {}      # audit event of a read -> time of its last audit entry


STATE = ServerState()
STATIC = {"/": "wealthview.html", "/wealthview.html": "wealthview.html", "/wf_logos.js": "wf_logos.js",
          "/wv.js": "wv.js", "/layout.js": "layout.js", "/flowpop.js": "flowpop.js", "/catrules.js": "catrules.js", "/groceries.js": "groceries.js", "/insurance.js": "insurance.js", "/setup.js": "setup.js", "/analytics.js": "analytics.js", "/insights.js": "insights.js", "/wv_demo.js": "wv_demo.js", "/wf_data.js": "wf_data.js", "/wv-intro.js": "wv-intro.js", "/version.js": "version.js", "/land-110m.json": "vendor/land-110m.json", "/favicon.ico": "icons/wealthview.ico"}
# Deny by default: every /api/ route needs a PIN session unless it is listed here, so a new route is protected without anyone
# having to remember to lock it. Static files are public except the ones in LOCKED_PATHS (answered as an empty script).
# The pairs are (HTTP method, path): a public path is public for that one method only.
PUBLIC_API = frozenset({("GET", "/api/ping"), ("GET", "/api/hb"), ("POST", "/api/bye"), ("POST", "/api/unlock")})
LOCKED_PATHS = frozenset({"/wf_data.js"})
# One route table per method: path -> (handler method name, audit event or None). GET handlers take no argument, POST handlers take the
# JSON body; a handler answers a body (sent as 200) or a (code, body) pair. Reads of private data are noted in the audit log (event name only,
# at most once per READ_AUDIT_EVERY_S, because the page polls them); the handlers of lookups and writes record their own audit entry.
GET_ROUTES: dict[str, tuple[str, str | None]] = {
    "/api/hb": ("_api_hb", None), "/api/ping": ("_api_ping", None), "/api/real": ("_api_real", "read_data"),
    "/api/live": ("_live", "read_live"), "/api/logo": ("_api_logo", None), "/api/company": ("_api_company", None),
    "/api/research": ("_api_research", None), "/api/netlog": ("_api_netlog", "read_netlog"), "/api/profile": ("_api_profile", "read_profile"),
    "/api/paypal": ("_api_paypal", "read_paypal"), "/api/src_logos": ("_api_src_logos", "read_src_logos"),
    "/api/ask/status": ("_api_ask_status", None), "/api/unusual_seen": ("_api_seen_get", "read_unusual_seen"),
    "/api/cat/overview": ("_api_cat_overview", "read_categories"), "/api/setup/state": ("_api_setup_state", "read_setup"),
    "/api/setup/browse": ("_api_setup_browse", "browse_folders"), "/api/setup/insurance": ("_api_setup_insurance", None),
    "/api/groceries": ("_api_groceries", "read_groceries"), "/api/watch": ("_api_watch", None), "/api/settings": ("_api_settings", None),
}
POST_ROUTES: dict[str, tuple[str, str | None]] = {
    "/api/bye": ("_api_bye", None), "/api/unlock": ("_api_unlock", None), "/api/lock": ("_api_lock", None),
    "/api/refresh": ("_api_refresh", None), "/api/quick": ("_api_quick", None), "/api/unusual_seen": ("_api_unusual_seen", "unusual_seen_add"),
    "/api/ask": ("_api_ask", None), "/api/ask/start": ("_api_ask_start", None), "/api/cat/set": ("_api_cat_set", None), "/api/cat/delete": ("_api_cat_delete", None),
    "/api/setup/source": ("_api_setup_source", None), "/api/setup/asset": ("_api_setup_asset", None),
    "/api/watch/set": ("_api_watch_set", None), "/api/settings/set": ("_api_settings_set", None),
    "/api/setup/balance": ("_api_setup_balance", None), "/api/setup/insurance/set": ("_api_setup_insurance_set", None), "/api/setup/answer": ("_api_setup_answer", None), "/api/setup/test": ("_api_setup_test", None),
}
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

    def _blocked(self, method: str, path: str) -> bool:
        """Central PIN gate: True (and the reply already sent) when (method, path) needs a session and there is none."""
        needs_pin = path in LOCKED_PATHS or (path.startswith("/api/") and (method, path) not in PUBLIC_API)
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
    def _api_paypal(self) -> Any:
        """the stored PayPal activity, newest first: rows [date, time, name, type, status, currency, gross, fee, net, balance] (read only)"""
        try:
            with open_data_db() as conn:
                total, rows = db_queries.paypal_activity(conn)
        except (sqlite3.Error, OSError) as exc:
            safenet.swallowed("server._api_paypal", exc)
            return {"ok": False, "error": "the PayPal activity could not be read yet"}
        return {"ok": True, "total": total, "rows": rows}

    @api_boundary()
    def _api_profile(self) -> Any:
        # what this installation shows (layout.js decides the boxes from it); the source folders stay on the server
        p = load_profile().to_dict()
        p["sources"] = [{"kind": s["kind"], "entity": s["entity"]} for s in p["sources"]]
        try:      # v1.20: what was set up in the dashboard counts too (a bank added there turns the cash boxes on)
            with open_data_db() as conn:
                found, p["typed"] = db_setup.detected_classes(conn), db_setup.has_typed(conn)
            p["asset_classes"] = [c for c in db_setup.CLASS_ORDER if c in set(p["asset_classes"]) | set(found)]
        except (sqlite3.Error, OSError, ValueError) as exc:      # no database yet: the installer's choice stands
            safenet.swallowed("server._api_profile", exc)
            p["typed"] = False
        return p

    @api_boundary(nodes=[])
    def _api_netlog(self) -> Any:
        q = self._query()
        old = (q.get("sig") or [""])[0]
        if (q.get("wait") or [""])[0] == "1" and old and old == netlog.sig():
            netlog.wait(old, NETLOG_WAIT_S)          # long poll: answers as soon as a new connection is logged
        return netlog.snapshot()

    def _api_real(self) -> Any:
        f = paths.data_path("data.json")
        if not f.exists():
            return 404, {"error": "no data yet - press REFRESH"}
        return f.read_bytes()      # the document itself (data.json), not an envelope

    def _read_audit(self, event: str) -> None:
        """Note a read of private data in the audit log, at most once per READ_AUDIT_EVERY_S per event (the page re-reads often)."""
        now = time.time()
        if now - STATE.read_audit.get(event, 0.0) >= READ_AUDIT_EVERY_S:
            STATE.read_audit[event] = now
            audit.record(event)

    def _reply(self, result: Any) -> None:
        """Send a handler's answer: a (code, body) pair as it is, anything else as 200."""
        if isinstance(result, tuple):
            return self._send(*result)
        return self._send(200, result)

    def _route(self, method: str) -> None:
        """The one request path for GET and POST: host check, PIN gate, route table lookup, audit of a read, handler, reply."""
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        path = self.path.split("?")[0]
        if self._blocked(method, path):
            return
        if method == "GET" and path in STATIC:
            return self._static(STATIC[path])
        route = (GET_ROUTES if method == "GET" else POST_ROUTES).get(path)
        body = self._json() if method == "POST" else None
        if route is None:
            return self._send(404, {"error": "not found"})
        name, read_event = route
        if read_event:
            self._read_audit(read_event) if method == "GET" else audit.record(read_event)      # reads: throttled; a write: every time
        handler = getattr(self, name)
        return self._reply(handler(body) if method == "POST" else handler())

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def _static(self, name: str) -> None:
        """send one of the page files (STATIC maps the URL to the file name)"""
        f = paths.BASE / name
        if f.exists():
            return self._send(200, f.read_bytes(), MIME.get(f.suffix, "application/octet-stream"))
        # a missing file is a 404 (never an empty 200): optional scripts carry an onerror handler in wealthview.html
        return self._send(404, {"error": "missing " + name})

    @api_boundary()
    def _api_hb(self) -> dict[str, Any]:
        STATE.life.heartbeat((self._query().get("id") or ["?"])[0][:40])
        return {"ok": True}

    @api_boundary()
    def _api_ping(self) -> dict[str, Any]:
        return {"ok": True, "app": "WealthView", "version": paths.version()}

    @api_boundary()
    def _api_ask_status(self) -> dict[str, Any]:
        return ask.lm_status(config.load_config().get("ask", {}))

    @api_boundary()
    def _api_ask_start(self, body: dict[str, Any]) -> dict[str, Any]:
        """the ask box was clicked: start LM Studio now (it no longer starts with the dashboard)"""
        return ask.start_lmstudio(config.load_config().get("ask", {}))

    @api_boundary()
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
    def _api_bye(self, body: dict[str, Any]) -> dict[str, Any]:
        """the page was closed (sendBeacon): the server may stop after a short grace"""
        STATE.life.goodbye((self._query().get("id") or ["?"])[0][:40])
        return {"ok": True}

    def _api_unlock(self, body: dict[str, Any]) -> Any:
        return unlock_reply(body)      # (code, reply), or {ok: false, error} when the boundary caught an error

    def _unlock(self, body: dict[str, Any]) -> None:
        out = unlock_reply(body)
        return self._send(*out) if isinstance(out, tuple) else self._send(200, out)

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

    def _api_ask(self, body: dict[str, Any]) -> dict[str, Any]:
        q = str(body.get("question") or "").strip()
        audit.record("ask", f"{len(q)} characters")
        return self._ask_reply(q, body)

    def _api_lock(self, body: dict[str, Any]) -> dict[str, Any]:
        """sign out: the session token stops working at once"""
        return lock_reply(self.headers.get("X-WV-Token", ""))

    def _lock(self) -> None:
        return self._send(200, lock_reply(self.headers.get("X-WV-Token", "")))

    @api_boundary()
    def _api_refresh(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._refresh(["--force-bank"] if body.get("force_bank") else None)       # the Refresh button asks the bank now, ignoring the 12 h wait

    @api_boundary()
    def _api_quick(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._refresh(["--quick"], jobs.QUICK_REFRESH_TIMEOUT_S)

    def _api_unusual_seen(self, body: dict[str, Any]) -> dict[str, Any]:
        keys = body.get("keys")
        return self._api_seen_add(keys if isinstance(keys, list) else [])

    @api_boundary()
    def _api_setup_state(self) -> dict[str, Any]:
        """Setup screen: the places the data comes from, the typed assets and accounts, the open questions."""
        with open_data_db() as conn:
            return db_setup.state(conn)

    @api_boundary()
    def _api_setup_browse(self) -> dict[str, Any]:
        """Folder picker: the sub-folders of ?path= (empty = start places)."""
        return folderbrowse.browse(param(self._query(), "path", 400))

    @api_boundary()
    def _api_setup_source(self, body: dict[str, Any]) -> dict[str, Any]:
        """Setup: add / rename / folder / subfolders / active / delete of one place (a bank, an investment, a crypto place)."""
        audit.record("setup_source", str(body.get("action")))
        with open_data_db() as conn:
            return db_setup.source_action(conn, body)

    @api_boundary()
    def _api_setup_test(self, body: dict[str, Any]) -> dict[str, Any]:
        """Setup (v1.22): try one API connection now and say what came back ({ok: True, works, text}); nothing is stored."""
        audit.record("setup_test")
        with open_data_db() as conn:
            got = exchanges.test_source(conn, body.get("id"))
        return {"ok": True, "works": bool(got["ok"]), "text": got["text"]}

    @api_boundary()
    def _api_setup_asset(self, body: dict[str, Any]) -> dict[str, Any]:
        """Setup: add / update / delete of a typed asset (house, loan, fund, other investment)."""
        audit.record("setup_asset", str(body.get("action")))
        with open_data_db() as conn:
            return db_setup.asset_action(conn, body)

    @api_boundary()
    def _api_groceries(self) -> dict[str, Any]:
        """Grocery orders (Knuspr) from the database tables groc_*, for the Groceries pop-up."""
        with open_data_db() as conn:
            groceries.import_pending(conn, paths.data_path("knuspr-import.json"))   # one-time carrier file: imported, then deleted
            return groceries.overview(conn)

    @api_boundary()
    def _api_watch(self) -> dict[str, Any]:
        """Shares you watch but do not own, with live prices (EUR) and the day change."""
        return watchlist.prices()

    @api_boundary()
    def _api_watch_set(self, body: dict[str, Any]) -> dict[str, Any]:
        """Setup: find / add / delete one share to watch (a lookup of a name sends only that name to Yahoo)."""
        audit.record("watch_" + str(body.get("action")))
        return watchlist.action(body)

    @api_boundary()
    def _api_settings(self) -> dict[str, Any]:
        """Setup: the few settings that can be changed here, with their current values."""
        return watchlist.settings_state()

    @api_boundary()
    def _api_settings_set(self, body: dict[str, Any]) -> dict[str, Any]:
        """Setup: change one setting of config.json (checked against its allowed range)."""
        audit.record("setting_set", str(body.get("key")))
        return watchlist.settings_set(body)

    @api_boundary()
    def _api_setup_insurance(self) -> dict[str, Any]:
        """Setup (v1.33): the insurance folders (from config.json and the ones added here)."""
        from ..data.ingest import insurance as ins_ing
        with open_data_db() as conn:
            return dict(folders=ins_ing.list_folders(conn), config=[f for f in (config.load_config().get("insurance_folders") or []) if isinstance(f, str)])

    @api_boundary()
    def _api_setup_insurance_set(self, body: dict[str, Any]) -> dict[str, Any]:
        """Setup (v1.33): add / remove an insurance folder; adding one also switches the insurance box on."""
        from ..common.profile import save_profile
        from ..data.ingest import insurance as ins_ing
        audit.record("setup_insurance", str(body.get("action")))
        with open_data_db() as conn:
            r = ins_ing.folder_action(conn, body, dt.datetime.now().isoformat(timespec="seconds"))
        if r.get("ok") and body.get("action") == "add":
            p = load_profile()
            if not p.modules.get("insurance"):
                p.modules["insurance"] = True
                save_profile(p)
        return r

    @api_boundary()
    def _api_setup_balance(self, body: dict[str, Any]) -> dict[str, Any]:
        """Setup: the balance of an account whose files carry none."""
        audit.record("setup_balance")
        with open_data_db() as conn:
            return db_setup.balance_action(conn, body)

    @api_boundary()
    def _api_setup_answer(self, body: dict[str, Any]) -> dict[str, Any]:
        """Setup: the answer to one open question about a file."""
        audit.record("setup_answer")
        with open_data_db() as conn:
            return db_setup.answer(conn, body)

    @api_boundary()
    def _api_cat_overview(self) -> dict[str, Any]:
        """Merchants with their category and a few bookings each, for the category-correction pop-up (?only=sonstiges|all&q=)."""
        q = self._query()
        only = "all" if param(q, "only") == "all" else "sonstiges"
        with open_data_db() as conn:
            return catrules.overview(conn, only, param(q, "q", 60))

    @api_boundary()
    def _api_cat_set(self, body: dict[str, Any]) -> dict[str, Any]:
        """Saves one correction: scope 'merchant' (a rule for every booking of that merchant), 'text' (a keyword rule) or 'booking' (one booking; it is passed on to the similar bookings of that merchant)."""
        scope, cat = str(body.get("scope") or "merchant"), body.get("category")
        audit.record("category_set", scope)
        with open_data_db() as conn:
            if scope == "booking":
                return {"saved": True, **catrules.correct_booking(conn, str(body.get("key") or ""), str(cat or ""), str(body.get("name") or ""))}
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
        audit.record("refresh_quick" if args and "--quick" in args else "refresh_full")
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

"""
Ask box backend (v1.08): answers questions about your data with the LOCAL language model in LM Studio (OpenAI-compatible API on
127.0.0.1:1234) - nothing leaves the PC. The model gets the table layout and may reply with ONE ```sql block holding a SELECT; this module
runs it on a READ-ONLY connection and feeds the result back, then the model answers in plain words. The plain-text protocol works with
any model (no tool-calling support needed). The SQL is never trusted: see run_query().
"""
from __future__ import annotations
from typing import Any, Callable
import json, re, sqlite3, time, urllib.request, urllib.error
import datetime as dt
from pathlib import Path
from ..common import config, safenet
from ..common.types.research import AskResult, ChatMessage, QueryResult

LM_DEFAULT_URL = "http://127.0.0.1:1234/v1"      # LM Studio's local server
MAX_ROWS = 100
MAX_CHARS = 6000
TIME_LIMIT_S = 3.0
HIDDEN_TABLES = {"meta", "file_seen", "sqlite_sequence"}
# SQLite authorizer action codes. Named here because sqlite3.SQLITE_SELECT etc. only exist from Python 3.11 and we support 3.10.
SQLITE_READ, SQLITE_SELECT, SQLITE_FUNCTION, SQLITE_RECURSIVE = 20, 21, 31, 33
_OK_ACTIONS = {SQLITE_SELECT, SQLITE_READ, SQLITE_FUNCTION, SQLITE_RECURSIVE}      # nothing else may run


class SqlRefused(Exception):
    pass


def _authorizer(action: int, a1: str | None, a2: str | None, dbname: str | None, source: str | None) -> int:
    if action not in _OK_ACTIONS:
        return sqlite3.SQLITE_DENY
    if action == SQLITE_READ and a1 in HIDDEN_TABLES:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def check_sql(sql: str) -> str:
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise SqlRefused("empty query")
    if ";" in s:
        raise SqlRefused("only one statement is allowed")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise SqlRefused("only SELECT queries are allowed")
    return s


def run_query(db_path: str | Path, sql: str, max_rows: int = MAX_ROWS, time_limit: float = TIME_LIMIT_S) -> QueryResult:
    """-> dict(columns, rows, truncated). Read-only connection + authorizer (SELECT only) + row cap + time limit."""
    sql = check_sql(sql)
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.set_authorizer(_authorizer)
        t0 = time.time()
        conn.set_progress_handler(lambda: 1 if time.time() - t0 > time_limit else 0, 20000)
        try:
            cur = conn.execute(sql)
            rows = cur.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as e:
            msg = str(e)
            if "interrupted" in msg:
                msg = f"query took longer than {time_limit:.0f} s - make it simpler or add a filter"
            elif "not authorized" in msg or "prohibited" in msg:
                msg = "not allowed (read-only SELECT on the data tables only)"
            raise SqlRefused(msg) from e
        cols = [d[0] for d in (cur.description or [])]
        return dict(columns=cols, rows=[list(r) for r in rows[:max_rows]], truncated=len(rows) > max_rows)
    finally:
        conn.close()


def schema_text(db_path: str | Path) -> str:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        out = []
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if name in HIDDEN_TABLES or name.startswith("sqlite_"):
                continue
            cols = ", ".join(f"{c[1]} {c[2]}".strip() for c in conn.execute(f'PRAGMA table_info("{name}")'))
            out.append(f"{name}({cols})")
        return "\n".join(out)
    finally:
        conn.close()


GUIDE = """You are {owner}'s personal wealth analyst and investment adviser. You know their WHOLE portfolio (summary below) and can query their bookings database.
- Answer questions about their data, their whole portfolio, and general or specific investment questions. Give a real, reasoned opinion and concrete options (what you would do and why, risks, alternatives); do not refuse or hide behind generic disclaimers. Add at most one short line that this is not regulated advice, at the end.
- Numbers about THEIR money must come from the portfolio summary or a query result - never invent them. Market facts, prices and news you are not sure about: look them up.
- To look something up in the database, reply with ONLY one ```sql block containing a single SELECT (LIMIT <= 50 or aggregates). You get the result and may query again.
- To look something up on the web, reply with ONLY one line: SEARCH: <short search words>. You get the top results (title, link, snippet) and may search again. Search words must NEVER contain their balances or personal data. Cite the sources you used by name.
- At most 4 lookups in total. When you have enough, answer in plain English WITHOUT a sql block or SEARCH line: clear and compact (max ~250 words), amounts like 1.234 EUR, say which period or date numbers cover.
- Dates are ISO text (YYYY-MM-DD). In bookings.amount and spending.amount money OUT is negative.
- spending = real spending only (no income, no transfers, no card settlements, no investments), already categorised.
- monthly(month, item, amount): item is income, expense, savings or cat:<category>; amounts positive.
- bookings = every bank booking (kind: giro / card / tages / shares); paypal_tx = PayPal activity; depot_positions = securities per export date; trades = buys/sells.
- snapshots = values recorded on each refresh: scope total (key gross, net, net_after_tax, liabilities), class, position (key = WKN), coin. Only since WealthView started recording."""


def system_prompt(db_path: str | Path, today: dt.date | None = None, portfolio: str = "") -> str:
    today = today or dt.date.today()
    return GUIDE.replace("{owner}", config.owner_display() or "the user") + f"\nToday is {today.isoformat()}.\n\nPORTFOLIO:\n{portfolio or '(not available)'}\n\nTABLES:\n" + schema_text(db_path)


_SQL_BLOCK = re.compile(r"```(?:sql|sqlite)?\s*\n?(.*?)```", re.S | re.I)
_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)


def extract_sql(text: str) -> str | None:
    """The SELECT/WITH in the first code block of a reply, or None when the reply is a final answer."""
    for m in _SQL_BLOCK.finditer(text or ""):
        body = m.group(1).strip()
        if re.match(r"(?is)^(select|with)\b", body):
            return body
    return None


def clean_answer(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def format_result(res: QueryResult, max_chars: int = MAX_CHARS) -> str:
    if not res["columns"]:
        return "(no result)"
    lines = ["\t".join(res["columns"])] + ["\t".join("" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v)) for v in r) for r in res["rows"]]
    txt = "\n".join(lines)
    if len(txt) > max_chars:
        txt = txt[:max_chars] + "\n... (cut off)"
    if res["truncated"]:
        txt += f"\n... (only the first {len(res['rows'])} rows are shown)"
    return txt if res["rows"] else txt + "\n(0 rows)"


# ------------------------------------------------------------------ LM Studio
def lm_models(base: str, timeout: int = 3) -> list[str]:
    with safenet.urlopen(base.rstrip("/") + "/models", timeout) as r:
        return [m["id"] for m in json.loads(r.read().decode("utf-8")).get("data", [])]


def pick_model(base: str, wanted: str = "auto", prefer: str | None = None) -> str:
    """The configured model, or (auto) the loaded model matching `prefer` (e.g. Gemma 4), else the first loaded chat model."""
    if wanted and wanted != "auto":
        return wanted
    ids = [m for m in lm_models(base) if "embed" not in m.lower()]
    if not ids:
        raise RuntimeError("no model is loaded in LM Studio")
    if prefer:
        hit = [m for m in ids if re.search(prefer, m, re.I)]
        if hit:
            return hit[0]
    return ids[0]


class EmptyReply(RuntimeError):
    """LM Studio answered but sent no text. Typical for "thinking" models (Gemma 4 and others): they spend the whole token allowance on
    reasoning, which LM Studio files under reasoning_content, and message.content stays empty (finish_reason "length")."""


DEFAULT_MAX_TOKENS = 4096        # v1.17: was 900 - far too little for a thinking model, whose reasoning counts against it
DEFAULT_TIMEOUT_S = 180


def lm_chat(base: str, model: str, messages: list[ChatMessage], timeout: int = DEFAULT_TIMEOUT_S, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                                 data=json.dumps(dict(model=model, messages=messages, temperature=0.1, max_tokens=max_tokens, stream=False)).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with safenet.urlopen(req, timeout) as r:
        j = json.loads(r.read().decode("utf-8"))
    ch = j["choices"][0]
    msg = ch.get("message") or {}
    text = msg.get("content") or ""
    if not clean_answer(text):
        why = str(ch.get("finish_reason") or "?")
        thought = len(msg.get("reasoning_content") or msg.get("reasoning") or "")
        raise EmptyReply(f"the model sent no text (finish_reason={why}, reasoning={thought} characters, max_tokens={max_tokens})")
    return text


# What asking LM Studio for its model can raise: network/JSON errors, "no model loaded" (RuntimeError), odd answers.
_LM_ERRORS = (*safenet.NET_ERRORS, RuntimeError, KeyError, TypeError, AttributeError)


def lm_status(cfg: dict[str, Any]) -> dict[str, Any]:
    """What the page shows next to the box: is LM Studio reachable, which model."""
    base = cfg.get("url", LM_DEFAULT_URL)
    try:
        return dict(ok=True, model=pick_model(base, cfg.get("model", "auto"), cfg.get("model_match")), url=base)
    except _LM_ERRORS as e:
        return dict(ok=False, url=base, error="LM Studio is not reachable or has no model loaded (start LM Studio and load a model).", detail=str(e))


def _start_messages(db_path: str | Path, question: object, history: object, today: dt.date | None, portfolio: str = "") -> list[ChatMessage]:
    """system prompt (reads the database), the last 6 valid chat turns, then the new question"""
    msgs: list[ChatMessage] = [dict(role="system", content=system_prompt(db_path, today, portfolio))]
    for h in (history if isinstance(history, list) else [])[-6:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append(dict(role=h["role"], content=str(h["content"])[:2000]))
    msgs.append(dict(role="user", content=str(question)[:1000]))
    return msgs


def _run_and_report(db_path: str | Path, sql: str, queries: list[dict[str, Any]], msgs: list[ChatMessage]) -> None:
    """run one SELECT of the model; note it in `queries` and add the result (or the refusal) to the chat for the next round"""
    try:
        res = run_query(db_path, sql)
        queries.append(dict(sql=sql, rows=len(res["rows"]), truncated=res["truncated"]))
        msgs.append(dict(role="user", content="RESULT:\n" + format_result(res) + "\n\nContinue: query again if you need more, otherwise answer now (no sql block)."))
    except SqlRefused as e:
        queries.append(dict(sql=sql, error=str(e)))
        msgs.append(dict(role="user", content=f"The query was refused: {e}. Fix it or answer without it."))


_SEARCH = re.compile(r"^\s*SEARCH:\s*(.+?)\s*$", re.M | re.I)


def _run_search(q: str, searches: list[dict[str, Any]], sources: list[dict[str, str]], msgs: list[ChatMessage], fetch: Callable[[str], list[dict[str, str]]]) -> None:
    res = fetch(q)
    searches.append(dict(q=q, results=len(res)))
    for r in res:
        if not any(x["url"] == r["url"] for x in sources):
            sources.append(dict(title=r["title"], url=r["url"]))
    body = "\n".join(f"- {r['title']} ({r['url']}): {r['snippet']}" for r in res) or "no results (offline?) - say that you could not check online"
    msgs.append(dict(role="user", content="WEB RESULTS for '" + q + "':\n" + body + "\n\nContinue: search or query again if needed, otherwise answer now."))


def answer(db_path: str | Path, question: object, history: object = None, cfg: dict[str, Any] | None = None,
           chat: Callable[[list[ChatMessage]], str] | None = None, today: dt.date | None = None,
           portfolio: str = "", search: Callable[[str], list[dict[str, str]]] | None = None) -> AskResult:
    """-> dict(ok, answer, queries=[dict(sql, rows|error)], model). `chat(messages)->text` can be injected (tests)."""
    cfg = cfg or {}
    base = cfg.get("url", LM_DEFAULT_URL)
    rounds = int(cfg.get("max_rounds", 4))
    model: str | None = None
    if chat is None:
        try:
            model = pick_model(base, cfg.get("model", "auto"), cfg.get("model_match"))
        except _LM_ERRORS as e:
            return dict(ok=False, error="LM Studio is not reachable or has no model loaded. Start LM Studio and load a model.", detail=str(e))
        chat = lambda msgs: lm_chat(base, model, msgs, int(cfg.get("timeout_s", DEFAULT_TIMEOUT_S)), int(cfg.get("max_tokens", DEFAULT_MAX_TOKENS)))
    queries: list[dict[str, Any]] = []
    searches: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []
    if search is None:
        from .advisor import web_search
        search = web_search
    try:
        msgs = _start_messages(db_path, question, history, today, portfolio)     # reads the database: inside the try
        for _ in range(rounds + 1):
            text = clean_answer(chat(msgs))
            sql = extract_sql(text)
            sm = None if sql else _SEARCH.search(text)
            if (sql or sm) and len(queries) + len(searches) >= rounds:
                break                              # the model still wants another lookup but the allowance is used up
            if not sql and not sm:
                final = _SQL_BLOCK.sub("", _SEARCH.sub("", text)).strip() or text
                if not final:
                    return dict(ok=False, error="The model sent an empty answer - ask again or load a different model.", queries=queries)
                return dict(ok=True, answer=final, queries=queries, searches=searches, sources=sources, model=model)
            msgs.append(dict(role="assistant", content=text))
            if sql:
                _run_and_report(db_path, sql, queries, msgs)
            elif sm:
                _run_search(sm.group(1), searches, sources, msgs, search)
        return dict(ok=True, answer="I could not finish within the allowed number of lookups - try a narrower question.", queries=queries, searches=searches, sources=sources, model=model)
    except EmptyReply as e:
        return dict(ok=False, error="The model used up its answer length while thinking and sent no text. Ask again, or raise ask.max_tokens in config.json.", detail=str(e), queries=queries)
    except urllib.error.URLError as e:
        return dict(ok=False, error="LM Studio did not answer: " + str(e), queries=queries)
    except Exception as e:      # broad on purpose: server endpoint, any failure is shown to the user as an error answer, not a crash
        return dict(ok=False, error="The model call failed: " + str(e), queries=queries)

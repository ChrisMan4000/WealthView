"""Insurance (v1.33), part 2: the optional local-model reader (LM Studio, 127.0.0.1 only - nothing leaves the PC) and the dashboard block `data.insurance`.
Private edition: the model may be started for this (a Refresh with new or changed insurance files). Public edition: the model is used only when it
already answers; otherwise the plain-pattern facts from data/ingest/insurance.py are shown (no coverage table then)."""
from __future__ import annotations
import datetime as dt
import json, re, time
from typing import Any

from ..common import safenet
from ..data.ingest import insurance as ins
from . import ask

REMIND_DAYS = 14
WAIT_FOR_MODEL_S = 60
RUN_BUDGET_S = 100
MODEL_CHARS_PER_FILE = 3500
_FIELDS = ("company", "kind", "policy_no", "start_date", "end_date", "auto_renew", "premium", "interval", "summary", "included", "excluded", "cancelled", "in_force")
SYSTEM = ("You read German insurance papers and answer with ONE short JSON object and nothing else. Do not deliberate at length: read, then answer. "
          "Use only what the papers say; null when not stated; never invent. Keys: company (insurer's short name), kind (short English type, e.g. Liability), "
          "in_force (true when the papers show a contract in force; false for only an application, an old offer or an ended contract), "
          "summary (English, at most 45 words: what is insured, the sum insured, key conditions), "
          "included (at most 8 short English strings: covered items with limits), excluded (at most 6 short English strings: exclusions, deductibles, waiting periods).")


def _json_of(text: str) -> dict[str, Any] | None:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        v = json.loads(text[a:b + 1])
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def _clean(v: dict[str, Any]) -> dict[str, Any]:
    """Keep only well-formed values from the model's answer."""
    out: dict[str, Any] = {}
    for k in ("company", "kind", "policy_no", "summary"):
        if isinstance(v.get(k), str) and v[k].strip():
            out[k] = v[k].strip()[:600]
    for k in ("start_date", "end_date"):
        if isinstance(v.get(k), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v[k]):
            try:
                dt.date.fromisoformat(v[k])
                out[k] = v[k]
            except ValueError:
                pass
    for k in ("auto_renew", "cancelled", "in_force"):
        if isinstance(v.get(k), bool):
            out[k] = v[k]
    if isinstance(v.get("premium"), (int, float)) and not isinstance(v.get("premium"), bool) and 0 < v["premium"] < 100000:
        out["premium"] = round(float(v["premium"]), 2)
    if v.get("interval") in ins.INTERVAL_MONTHS:
        out["interval"] = v["interval"]
    for k, cap in (("included", 12), ("excluded", 10)):
        if isinstance(v.get(k), list):
            out[k] = [str(x).strip()[:160] for x in v[k] if isinstance(x, (str, int, float)) and str(x).strip()][:cap]
    return out


class ModelReader:
    """Reads a contract group through the local model. available() is checked once per run (private edition: may start LM Studio and wait)."""

    def __init__(self, cfg: dict[str, Any], allow_start: bool, sleep: Any = time.sleep, wait_s: int = WAIT_FOR_MODEL_S, budget_s: int = RUN_BUDGET_S,
                 clock: Any = time.monotonic) -> None:
        self.cfg, self.allow_start, self._sleep, self._wait_s = cfg, allow_start, sleep, wait_s
        self._clock, self._deadline = clock, clock() + budget_s       # one Refresh must stay inside the 240 s job limit: the rest is read at the next Refresh
        self._ok: bool | None = None
        self.started = False

    def available(self) -> bool:
        if self._clock() > self._deadline:
            return False
        if self._ok is not None:
            return self._ok
        ok = bool(ask.lm_status(self.cfg).get("ok"))
        if not ok and self.allow_start:
            r = ask.start_lmstudio(self.cfg)
            self.started = bool(r.get("ok"))
            waited = 0
            while self.started and not ok and waited < self._wait_s:
                self._sleep(5)
                waited += 5
                ok = bool(ask.lm_status(self.cfg).get("ok"))
        self._ok = ok
        return ok

    def __call__(self, name: str, docs: list[tuple[str, str]], facts: dict[str, Any]) -> dict[str, Any] | None:
        base = self.cfg.get("url", ask.LM_DEFAULT_URL)
        model = ask.pick_model(base, self.cfg.get("model", "auto"), self.cfg.get("model_match"))
        raw = None
        for chars in (MODEL_CHARS_PER_FILE, 1500, 700):        # a thinking model can burn all tokens on long text: retry shorter
            body = "\n\n".join(f"=== {n}\n{t[:chars]}" for n, t in docs)
            msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Folder: {name}\n\n{body}"}]
            try:
                raw = ask.lm_chat(base, model, msgs, timeout=int(max(120, min(900, self._deadline - self._clock() + 600))), max_tokens=12000)       # type: ignore[arg-type]
                break
            except (*ask._LM_ERRORS, ask.EmptyReply) as e:
                safenet.swallowed("insurance.model_call", e)
        if raw is None:
            return None
        j = _json_of(ask.clean_answer(raw))
        return _clean(j) if j else None


def logo_extras(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Logo keys -> domains for the insurers (the logo build fetches them like merchant logos)."""
    out: dict[str, str] = {}
    for r in rows:
        d = ins.company_domain(r.get("company") or "")
        if d and r.get("company"):
            out["ins:" + r["company"]] = d
    return out


_UML = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})
_FUNDS = ("bkk", "aok", "barmer", "techniker", "dak", "ikk", "mkk")
_PERIOD_DAYS = {"monthly": 30, "quarterly": 91, "half-yearly": 182, "yearly": 365}


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").translate(_UML).lower())


def _interval_of(dates: list[dt.date]) -> str:
    gaps = sorted((b - a).days for a, b in zip(dates, dates[1:]))
    g = gaps[len(gaps) // 2]
    return "monthly" if g <= 45 else "quarterly" if g <= 120 else "half-yearly" if g <= 240 else "yearly"


def apply_bookings(conn: Any, rows: list[dict[str, Any]], today: dt.date) -> list[dict[str, Any]]:
    """Bank bookings tell the real premium: payments to the insurer (matched by company name or policy number) give amount, interval and the next due date.
    Needs 2+ payments and a recent one; stale payments change nothing (e.g. a health fund taken from the salary). A recent payment also revives a contract the papers called ended."""
    try:
        pays = [(dt.date.fromisoformat(d), _norm((c or "") + (u or "")), -a) for d, c, u, a in conn.execute("SELECT date, counterparty, purpose, amount FROM bookings WHERE amount < 0 ORDER BY date")]
    except Exception as e:                                  # no bookings table / odd rows: the papers alone are fine
        safenet.swallowed("insurance.bookings", e)
        return rows
    for r in rows:
        extra = [_norm(x) for x in r.get("match") or [] if len(_norm(x)) >= 5]
        keys = extra + [k for k, n in ((_norm(r.get("company") or ""), 3), (_norm(r.get("policy_no") or ""), 5)) if len(k) >= n]
        statutory = any(f in _norm(r.get("company") or "") for f in _FUNDS)            # a health fund often debits under its brand
        if statutory:
            keys.append("krankenkasse")
            r["kind"] = "Health (statutory)"
        hit = {}
        for d, hay, amt in pays:
            if any(k in hay for k in keys):
                hit[d] = amt                                # one payment per day
        if len(hit) < 2:
            continue
        dates = sorted(hit)[-6:]
        interval = _interval_of(dates)
        step = dt.timedelta(days=_PERIOD_DAYS[interval])
        if (today - dates[-1]) > step * 1.5 + dt.timedelta(days=30):
            continue                                        # stopped paying
        r["premium"], r["interval"] = round(hit[dates[-1]], 2), interval
        r["paid_from_bookings"] = True
        if r.get("status") == "ended":
            r["status"], r["end_date"], r["auto_renew"] = "active", None, 1
        if not r.get("end_date") and interval in ("yearly", "half-yearly"):       # monthly / quarterly contracts just run on: no end date
            nxt = dates[-1] + step
            while nxt < today:
                nxt += step
            r["end_date"], r["auto_renew"] = nxt.isoformat(), 1
    return rows


def yearly_renewal(rows: list[dict[str, Any]], today: dt.date) -> list[dict[str, Any]]:
    """A yearly premium with no written end: the contract renews on its yearly anniversary (of the start date) - next one is the end shown."""
    for r in rows:
        if r.get("status") == "ended" or r.get("end_date") or r.get("interval") != "yearly" or not r.get("start_date"):
            continue
        try:
            e = dt.date.fromisoformat(r["start_date"])
            while e <= today:
                e = e.replace(year=e.year + 1, day=28) if (e.month, e.day) == (2, 29) else e.replace(year=e.year + 1)
        except ValueError:
            continue
        r["end_date"], r["auto_renew"] = e.isoformat(), 1
    return rows


def rows_now(conn: Any, today: dt.date, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The stored contracts, minus the ones the user hid (config insurance_hide: names) plus the ones that exist only in the bank bookings
    (config insurance_manual: [{name, company, kind, match: [text in the booking]}] - no papers, no end date), with real premiums from the bookings."""
    from ..common import config
    cfg = cfg if cfg is not None else config.load_config()
    hide = {str(h).strip().lower() for h in (cfg.get("insurance_hide") or [])}
    rows = [r for r in ins.load_rows(conn) if (r.get("name") or "").strip().lower() not in hide]
    for m in cfg.get("insurance_manual") or []:
        if isinstance(m, dict) and m.get("name"):
            rows.append(dict(gkey="manual:" + str(m["name"]), name=m["name"], company=m.get("company") or m["name"], kind=m.get("kind") or "", status="active", end_date=None,
                             start_date=None, auto_renew=0, reader="bookings", summary_hint=1, match=[str(x) for x in m.get("match") or []], summary=str(m.get("summary") or "Premium taken from your bank bookings; no papers needed."), included=list(m.get("included") or []), excluded=list(m.get("excluded") or [])))
    return yearly_renewal(apply_bookings(conn, rows, today), today)


def build_block(rows: list[dict[str, Any]], today: dt.date, rep: dict[str, Any] | None = None, remind_days: int = REMIND_DAYS) -> dict[str, Any]:
    """The `insurance` block of data.json: active contracts with timeline and monthly premium, the reminders (<= remind_days before the end)."""
    items: list[dict[str, Any]] = []
    ended = 0
    for r in rows:
        if r.get("status") == "ended":
            ended += 1
            continue
        end = dt.date.fromisoformat(r["end_date"]) if r.get("end_date") else None
        start = dt.date.fromisoformat(r["start_date"]) if r.get("start_date") else None
        term_start = start
        if end and r.get("auto_renew"):
            term_start = end.replace(year=end.year - 1) if end.month != 2 or end.day != 29 else end.replace(year=end.year - 1, day=28)      # the current year of an auto-renewing contract
        elapsed = None
        if end and term_start and end > term_start:
            elapsed = max(0.0, min(1.0, (today - term_start).days / (end - term_start).days))
        days = (end - today).days if end else None
        items.append(dict(id=r["gkey"], name=r.get("name"), company=r.get("company") or r.get("name"), kind=r.get("kind"), policy_no=r.get("policy_no"),
                          start=r.get("start_date"), end=r.get("end_date"), term_start=term_start.isoformat() if term_start else None, elapsed=elapsed, days_left=days,
                          auto_renew=bool(r.get("auto_renew")), status=r.get("status"), premium=r.get("premium"), interval=r.get("interval"),
                          monthly=ins.monthly_of(r.get("premium"), r.get("interval")), summary=r.get("summary") or "", included=r.get("included") or [],
                          excluded=r.get("excluded") or [], reader=r.get("reader"), n_files=r.get("n_files"), logo="ins:" + (r.get("company") or ""), updated=r.get("updated_at")))
    items.sort(key=lambda i: (i["days_left"] is None, i["days_left"] if i["days_left"] is not None else 0, i["name"] or ""))
    due = [i["id"] for i in items if i["days_left"] is not None and 0 <= i["days_left"] <= remind_days]
    monthly = round(sum(i["monthly"] or 0 for i in items), 2)
    return dict(items=items, monthly_total=monthly, yearly_total=round(monthly * 12, 2), active=len(items), ended=ended, remind_days=remind_days, due=due,
                pending_model=int((rep or {}).get("pending_model", 0)), folders=int((rep or {}).get("folders", 0)), errors=list((rep or {}).get("errors", [])),
                asof=today.isoformat())


JOB_LOCK = "insurance_job.json"          # data/: {"started": iso, "ended": iso|None, "left": pending groups after the job, "retry_after": iso|None}
JOB_STALE_S = 3 * 3600
RETRY_AFTER_FAIL_S = 6 * 3600


def _job_state() -> dict[str, Any]:
    from ..common.paths import data_path
    try:
        return dict(json.loads(data_path(JOB_LOCK).read_text("utf-8")))
    except (OSError, ValueError, TypeError):
        return {}


def _job_write(state: dict[str, Any]) -> None:
    from ..common.fileio import write_atomic
    from ..common.paths import data_path
    write_atomic(data_path(JOB_LOCK), json.dumps(state))


def _job_running(st: dict[str, Any], now: dt.datetime) -> bool:
    try:
        return bool(st.get("started")) and not st.get("ended") and (now - dt.datetime.fromisoformat(st["started"])).total_seconds() < JOB_STALE_S
    except (ValueError, TypeError):
        return False


def spawn_job(cfg: dict[str, Any], private: bool, new_files: bool, now: dt.datetime) -> str:
    """Starts the model reading in a detached process (it can take many minutes; a Refresh must stay short). Returns 'started', 'running' or 'off'.
    Private edition: the job may start LM Studio. Public edition: only when the model already answers. Not again for 6 h after a job that left work undone,
    unless new or changed files arrived."""
    import subprocess, sys
    from ..common import paths
    st = _job_state()
    if _job_running(st, now):
        return "running"
    if st.get("retry_after") and not new_files:
        try:
            if now < dt.datetime.fromisoformat(st["retry_after"]):
                return "off"
        except (ValueError, TypeError):
            pass
    if not private and not ask.lm_status(cfg.get("ask", {}) or {}).get("ok"):
        return "off"
    flags = (0x00000008 | 0x08000000 | 0x00000200) if sys.platform == "win32" else 0         # DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    try:
        _job_write(dict(started=now.isoformat(timespec="seconds"), ended=None, left=None, retry_after=None))
        subprocess.Popen([sys.executable, str(paths.BASE / "refresh.py"), "--insurance-model"], cwd=str(paths.BASE), creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        safenet.swallowed("insurance.spawn_job", e)
        return "off"
    return "started"


def job_main() -> None:
    """`refresh.py --insurance-model`: read the groups that have no model reading yet (new / changed files first), then refresh the insurance block of data.json."""
    from ..common import config
    from ..common.fileio import write_atomic
    from ..common.paths import data_path
    from ..common.profile import load_profile
    from ..data.ingest import db_schema
    cfg, prof = config.load_config(), load_profile()
    t0 = dt.datetime.now()
    folders = [f.strip() for f in (cfg.get("insurance_folders") or []) if isinstance(f, str) and f.strip()]
    left = 0
    try:
        conn = db_schema.connect(data_path(db_schema.DB_NAME))
        try:
            reader = ModelReader(cfg.get("ask", {}) or {}, allow_start=getattr(prof, "edition", "") == "private", budget_s=2 * 3600, wait_s=180)
            rep = ins.sync(conn, folders, t0.date(), t0.isoformat(timespec="seconds"), use_model=reader, budget=30)
            left = int(rep.get("pending_model", 0))
            block = build_block(rows_now(conn, t0.date()), t0.date(), rep, int(cfg.get("insurance_remind_days", REMIND_DAYS)))
            block["configured"] = True
            f = data_path("data.json")
            if f.exists():
                data = json.loads(f.read_text("utf-8"))
                data["insurance"] = block
                write_atomic(f, json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        finally:
            conn.close()
    finally:
        ended = dt.datetime.now()
        _job_write(dict(started=t0.isoformat(timespec="seconds"), ended=ended.isoformat(timespec="seconds"), left=left,
                        retry_after=(ended + dt.timedelta(seconds=RETRY_AFTER_FAIL_S)).isoformat(timespec="seconds") if left else None))


def rebuild_block(conn: Any, today: dt.date, old: dict[str, Any] | None, remind_days: int = REMIND_DAYS) -> dict[str, Any]:
    """The light refresh: the block again from the database (a background model reading may have finished), keeping the run facts of the old block."""
    old = old or {}
    rep = dict(pending_model=sum(1 for r in rows_now(conn, today) if r.get("reader") not in ("model", "bookings") and r.get("status") != "ended"), folders=old.get("folders", 0), errors=old.get("errors", []))
    b = build_block(rows_now(conn, today), today, rep, remind_days)
    b["configured"] = old.get("configured", True)
    st = _job_state()
    b["model_job"] = "running" if _job_running(st, dt.datetime.now()) else old.get("model_job", "off")
    return b


def run(conn: Any, profile: Any, today: dt.date, now: str, cfg: dict[str, Any] | None = None, reader: Any = None) -> dict[str, Any] | None:
    """The refresh stage: read the insurance folders (new or changed files only, plain patterns - fast) and build data.insurance. None when the module is off
    or there is no database. The local model reading (summary, included / excluded) runs afterwards in a detached job (spawn_job); `reader` (tests, tools) reads inline."""
    from ..common import config
    cfg = cfg if cfg is not None else config.load_config()
    if conn is None or not getattr(profile, "modules", {}).get("insurance", True):
        return None
    folders = ins.all_folders(conn, [f for f in (cfg.get("insurance_folders") or []) if isinstance(f, str)])
    rep: dict[str, Any] = dict(folders=0, pending_model=0, errors=[])
    job = "off"
    if folders:
        rep = ins.sync(conn, folders, today, now, use_model=reader)
        if rep["pending_model"] and reader is None:
            job = spawn_job(cfg, getattr(profile, "edition", "") == "private", bool(rep["analysed"]), dt.datetime.now())
        elif rep["pending_model"] and _job_running(_job_state(), dt.datetime.now()):
            job = "running"
    block = build_block(rows_now(conn, today) if folders else [], today, rep, int(cfg.get("insurance_remind_days", REMIND_DAYS)))
    block["configured"] = bool(folders)
    block["model_job"] = job
    return block

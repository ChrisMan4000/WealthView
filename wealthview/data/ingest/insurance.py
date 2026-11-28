"""Insurance folders (v1.33): every sub-folder of an insurance folder is one contract group (company / product); loose PDFs in the folder itself
are one group each. The folders are read READ-ONLY. A group is read again only when one of its files is new or changed (name, size, time).
Part 1 here: scan, PDF text, plain regex extraction, database. The optional local-model reader and the dashboard block are in analysis/insurance.py.
Standard library only (PDF text through fund_files.pdf_text: pdftotext, pypdf or the built-in reader)."""
from __future__ import annotations
import datetime as dt
import hashlib, json, re, sqlite3
from pathlib import Path
from typing import Any, Callable

from ...common import safenet
from .fund_files import pdf_text

MAX_FILES_PER_GROUP = 3          # the newest few contract documents of a group are read, not all of the (often 50+) files
MAX_CHARS_PER_FILE = 30000
MAX_GROUPS = 60
ANALYSIS_VERSION = 3            # part of every group signature: a change of the reading rules makes all groups read again once
STALE_DAYS = 730                 # no end date and no paper for two years: not counted as active
SHAKY_DAYS = 548                 # the model says "not in force" but a paper is younger than this: believe the folder, not the model
SKIP_NAMES = re.compile(r"beratungsprotokoll|beratungsverzicht|widerruf|einkommen|erwerbsbiografie|zuzahlung|resume|kuendigungshilfe", re.I)
# how much a file name says "this is the contract document" (higher = read first)
_NAME_SCORE = ((re.compile(r"versicherungsschein|vschein|police|vertrag\b|vertrag ", re.I), 6), (re.compile(r"beitragsanpassung|beitragsrechnung|rechnung", re.I), 4),
               (re.compile(r"k[uü]ndigung", re.I), 5), (re.compile(r"highlight|produktinformation|informationsblatt|ipid|leistungsein", re.I), 3),
               (re.compile(r"antrag|bedingungen|avb|aub", re.I), 1))
KINDS = (("Liability", r"haftpflicht|\bphv\b"), ("Accident", r"unfall"), ("Travel health", r"reise.?kranken|auslands.?(reise)?kv|auslandsreise|travelsecure|jahresversicherung"),
         ("Dental / supplementary health", r"zahn|erg[aä]nzungsversicherung"), ("Health (statutory)", r"\bbkk\b|krankenkasse|pflichtversicher|mkk"),
         ("Household contents", r"hausrat"), ("Legal protection", r"rechtsschutz"), ("Disability", r"berufsunf"), ("Life", r"lebensversicherung|risikoleben"),
         ("Car", r"kfz|autoversicherung"), ("Health", r"krankenversicherung|\bkv\b"))
INSURERS = {  # name -> web domain (for the logo; the name is the only thing ever sent out, and only to find the logo)
    "adam riese": "adam-riese.de", "allianz": "allianz.de", "barmenia": "barmenia.de", "bkk vbu": "bkk-vbu.de", "mkk": "bkk-vbu.de", "hansemerkur": "hansemerkur.de",
    "dkv": "dkv.de", "ammerl": "ammerlaender-versicherung.de", "würzburger": "wuerzburger.de", "wuerzburger": "wuerzburger.de", "huk": "huk.de", "axa": "axa.de",
    "ergo": "ergo.de", "generali": "generali.de", "debeka": "debeka.de", "signal iduna": "signal-iduna.de", "techniker": "tk.de", "aok": "aok.de", "barmer": "barmer.de",
    "r+v": "ruv.de", "devk": "devk.de", "cosmos": "cosmosdirekt.de", "check24": "check24.de", "ammerländer": "ammerlaender-versicherung.de"}
INTERVAL_MONTHS = {"yearly": 12, "half-yearly": 6, "quarterly": 3, "monthly": 1}

SCHEMA = """
CREATE TABLE IF NOT EXISTS insurances(
  gkey TEXT PRIMARY KEY, name TEXT, company TEXT, kind TEXT, policy_no TEXT, start_date TEXT, end_date TEXT, auto_renew INTEGER DEFAULT 0, status TEXT,
  premium REAL, interval TEXT, summary TEXT, included TEXT, excluded TEXT, reader TEXT, sig TEXT, folder TEXT, n_files INTEGER, updated_at TEXT);
CREATE TABLE IF NOT EXISTS insurance_files(path TEXT PRIMARY KEY, gkey TEXT, size INTEGER, mtime INTEGER);
CREATE TABLE IF NOT EXISTS insurance_folders(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, created TEXT);
"""


# ------------------------------------------------------------------ scanning (read only)
def _is_doc(p: Path) -> bool:
    return p.suffix.lower() == ".pdf" and not p.name.startswith(".")


def scan_group_files(folder: Path) -> dict[str, list[Path]]:
    """{group key: [pdf files]} for one insurance folder. Sub-folder -> one group (all PDFs below it); a loose PDF -> its own group."""
    groups: dict[str, list[Path]] = {}
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.lower())
    except OSError as e:
        safenet.swallowed("insurance.scan", e)
        return groups
    loose: dict[str, list[Path]] = {}
    for e in entries:
        try:
            if e.name.startswith("."):
                continue
            if e.is_dir():
                files = sorted((p for p in e.rglob("*") if p.is_file() and _is_doc(p)), key=lambda p: str(p).lower())
                if files:
                    groups[e.name] = files
            elif e.is_file() and _is_doc(e) and not SKIP_NAMES.search(e.name):
                loose.setdefault(re.sub(r"\s+\d{1,2}$|\s*\(\d+\)$", "", e.stem).strip(), []).append(e)      # "Rechnung_X 1.pdf" is a copy of "Rechnung_X.pdf"
        except OSError as exc:
            safenet.swallowed("insurance.scan", exc)
    for k, files in loose.items():
        groups["file: " + k] = files
    return dict(list(groups.items())[:MAX_GROUPS])


def _stat(p: Path) -> tuple[int, int]:
    st = p.stat()
    return int(st.st_size), int(st.st_mtime)


def group_sig(files: list[Path]) -> str:
    """Cheap fingerprint of a group: names, sizes, times (stat only, so a cloud-only OneDrive file is not downloaded just to look at it)."""
    h = hashlib.sha1(f"v{ANALYSIS_VERSION}\n".encode())
    for p in files:
        try:
            s, m = _stat(p)
        except OSError:
            continue
        h.update(f"{p.name}|{s}|{m}\n".encode("utf-8", "replace"))
    return h.hexdigest()


def newest_date(files: list[Path]) -> dt.date | None:
    """Date of the newest file of a group (stat only)."""
    ts = []
    for p in files:
        try:
            ts.append(_stat(p)[1])
        except OSError:
            pass
    return dt.date.fromtimestamp(max(ts)) if ts else None


def pick_docs(files: list[Path]) -> list[Path]:
    """The contract documents of a group worth reading: best-named first, newest first; skips advisory / unrelated papers."""
    def score(p: Path) -> tuple[int, int]:
        s = max([sc for rx, sc in _NAME_SCORE if rx.search(p.name)] or [0])
        try:
            return (s, _stat(p)[1])
        except OSError:
            return (s, 0)
    ok = [p for p in files if not SKIP_NAMES.search(p.name)] or files
    return sorted(ok, key=score, reverse=True)[:MAX_FILES_PER_GROUP]


def read_group_text(files: list[Path], reader: Callable[[Path], str] | None = None) -> list[tuple[str, str]]:
    """[(file name, text)] of the picked documents (empty text for a scan without a text layer is dropped)."""
    out: list[tuple[str, str]] = []
    reader = reader or pdf_text
    for p in pick_docs(files):
        try:
            t = reader(p)
        except (OSError, ValueError, RuntimeError) as e:
            safenet.swallowed("insurance.read", e)
            continue
        t = re.sub(r"[ \t]+", " ", t or "").strip()
        if len(t) > 40:
            out.append((p.name, t[:MAX_CHARS_PER_FILE]))
    return out


# ------------------------------------------------------------------ plain extraction (no model needed)
_DATE = r"(\d{1,2})\.(\d{1,2})\.(\d{4})"
_MONEY = r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*(?:€|EUR)"


def _iso(d: str, m: str, y: str) -> str | None:
    try:
        return dt.date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _money(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def guess_kind(text: str) -> str:
    low = text.lower()
    for name, rx in KINDS:
        if re.search(rx, low):
            return name
    return "Insurance"


def guess_company(name: str, text: str) -> str:
    low = (name + " " + text[:3000]).lower()
    for key in sorted(INSURERS, key=len, reverse=True):
        if key in low:
            return {"adam riese": "Adam Riese", "bkk vbu": "BKK VBU", "mkk": "BKK VBU", "hansemerkur": "HanseMerkur", "dkv": "DKV", "ammerl": "Ammerländer",
                    "würzburger": "Würzburger", "wuerzburger": "Würzburger", "r+v": "R+V", "signal iduna": "Signal Iduna"}.get(key, key.title())
    m = re.match(r"([A-ZÄÖÜ][\w.&-]+(?: [A-ZÄÖÜ][\w.&-]+)?)", name)
    return m.group(1) if m else name


def company_domain(company: str) -> str | None:
    low = company.lower()
    return next((d for k, d in INSURERS.items() if k in low), None)


def regex_extract(name: str, docs: list[tuple[str, str]], today: dt.date) -> dict[str, Any]:
    """Facts a plain pattern can find in German policy papers: policy number, start / end, premium + interval, cancelled or not.
    No coverage table - that needs the local model. Missing facts stay None."""
    text = "\n".join(t for _, t in docs)
    out: dict[str, Any] = dict(company=guess_company(name, text), kind=guess_kind(name + " " + text[:2500]), policy_no=None, start_date=None, end_date=None,
                               auto_renew=bool(re.search(r"verl[aä]ngert sich (?:automatisch|stillschweigend)|automatisch um (?:jeweils )?ein weiteres", text, re.I)),
                               premium=None, interval=None, cancelled=False)
    m = re.search(r"(?:Versicherungsschein|Vertrags|Policen?)[- ]?(?:Nr\.?|nummer)[:\s]*([A-Z0-9][\w./-]*\d[\w./-]{4,})", text, re.I)
    if m:
        out["policy_no"] = m.group(1).rstrip(".")
    m = re.search(r"BEGINN\s+ABLAUF.{0,160}?" + _DATE + r".{1,60}?" + _DATE, text, re.I | re.S)      # table header "BEGINN ABLAUF" above two dates
    if m:
        out["start_date"], out["end_date"] = _iso(*m.groups()[:3]), _iso(*m.groups()[3:])
    else:
        m = re.search(r"(?:Versicherungsbeginn|Vertragsbeginn|BEGINN|Beginn).{0,220}?" + _DATE, text, re.S)
        if m:
            out["start_date"] = _iso(*m.groups())
        ends = [_iso(*x.groups()) for x in re.finditer(r"(?:Ablauf|Vertragsende|Versicherungsende|endet mit Ablauf des)\D{0,40}?" + _DATE, text, re.I)]
        ends = [e for e in ends if e and (not out["start_date"] or e > out["start_date"])]
        if ends:
            out["end_date"] = max(ends)
    if any(re.search(r"k[uü]ndigungsbest", n, re.I) for n, _ in docs) or re.search(r"Sie haben Ihren Versicherungsschutz gek[uü]ndigt|Ihr Vertrag .{0,30}endet mit Ablauf", text, re.I):
        out["cancelled"] = True
    for label, interval in (("Jahresbeitrag|j[aä]hrlich|Jahresversicherung|Jahresprämie", "yearly"), ("Halbjahresbeitrag|halbj[aä]hrlich", "half-yearly"),
                            ("Quartalsbeitrag|viertelj[aä]hrlich", "quarterly"), ("Monatsbeitrag|monatlich|Monatsprämie", "monthly")):
        m = re.search(r"(?:" + label + r")[^\d\n]{0,70}?" + _MONEY, text, re.I)
        if m:
            out["premium"], out["interval"] = _money(m.group(1)), interval
            break
    m = re.search(r"\bGesamt(?:pr[aä]mie|beitrag)?:?[^\d\n]{0,60}?" + _MONEY, text)       # the gross total (with insurance tax) beats the net line
    if m and out["premium"] is not None and out["premium"] <= _money(m.group(1)) <= out["premium"] * 1.4:
        out["premium"] = _money(m.group(1))
    if out["premium"] is None:
        m = re.search(r"(?:Gesamt(?:beitrag)?|Beitrag|Prämie)[^\d\n]{0,50}?" + _MONEY, text, re.I)
        if m:
            out["premium"], out["interval"] = _money(m.group(1)), "yearly"
    return out


def settle_dates(start: str | None, end: str | None, auto_renew: bool, cancelled: bool, today: dt.date) -> tuple[str | None, str]:
    """(next end / renewal date, status). An auto-renewing contract whose written end has passed is rolled forward by whole years."""
    if not end and start and auto_renew and not cancelled:
        try:
            end = dt.date.fromisoformat(start).replace(year=dt.date.fromisoformat(start).year + 1).isoformat()      # a one-year term that renews by itself
        except ValueError:
            end = None
    if not end:
        return None, "ended" if cancelled else "active"
    try:
        e = dt.date.fromisoformat(end)
    except ValueError:
        return None, "active"
    if cancelled:
        return end, "ended" if e < today else "ending"
    if e < today:
        if not auto_renew:
            return end, "ended"
        while e < today:
            try:
                e = e.replace(year=e.year + 1)
            except ValueError:
                e = e.replace(year=e.year + 1, day=28)
    return e.isoformat(), "active"


def monthly_of(premium: float | None, interval: str | None) -> float | None:
    if premium is None or interval not in INTERVAL_MONTHS:
        return None
    return round(premium / INTERVAL_MONTHS[interval], 2)


# ------------------------------------------------------------------ database
def ensure(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def stored_sigs(conn: sqlite3.Connection) -> dict[str, tuple[str, str | None]]:
    """{group key: (signature, reader)} of what is already analysed."""
    ensure(conn)
    return {r[0]: (r[1] or "", r[2]) for r in conn.execute("SELECT gkey, sig, reader FROM insurances")}


def save_group(conn: sqlite3.Connection, gkey: str, folder: str, files: list[Path], sig: str, rec: dict[str, Any], now: str) -> None:
    ensure(conn)
    conn.execute("INSERT OR REPLACE INTO insurances(gkey,name,company,kind,policy_no,start_date,end_date,auto_renew,status,premium,interval,summary,included,excluded,reader,sig,folder,n_files,updated_at)"
                 " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (gkey, rec.get("name") or gkey, rec.get("company"), rec.get("kind"), rec.get("policy_no"), rec.get("start_date"), rec.get("end_date"),
                  1 if rec.get("auto_renew") else 0, rec.get("status"), rec.get("premium"), rec.get("interval"), rec.get("summary") or "",
                  json.dumps(rec.get("included") or [], ensure_ascii=False), json.dumps(rec.get("excluded") or [], ensure_ascii=False), rec.get("reader") or "regex",
                  sig, folder, len(files), now))
    conn.execute("DELETE FROM insurance_files WHERE gkey=?", (gkey,))
    for p in files:
        try:
            s, m = _stat(p)
        except OSError:
            continue
        conn.execute("INSERT OR REPLACE INTO insurance_files(path,gkey,size,mtime) VALUES(?,?,?,?)", (str(p), gkey, s, m))


def drop_missing(conn: sqlite3.Connection, keep: set[str]) -> int:
    """Groups whose folder is gone leave the table (the files themselves are never touched)."""
    ensure(conn)
    gone = [r[0] for r in conn.execute("SELECT gkey FROM insurances") if r[0] not in keep]
    for g in gone:
        conn.execute("DELETE FROM insurances WHERE gkey=?", (g,))
        conn.execute("DELETE FROM insurance_files WHERE gkey=?", (g,))
    return len(gone)


def load_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure(conn)
    rows = []
    for r in conn.execute("SELECT * FROM insurances ORDER BY name"):
        d = dict(r)
        for k in ("included", "excluded"):
            try:
                d[k] = json.loads(d.get(k) or "[]")
            except ValueError:
                d[k] = []
        rows.append(d)
    return rows


def sync(conn: sqlite3.Connection, folders: list[str], today: dt.date, now: str, use_model: Any = None, budget: int = 12) -> dict[str, Any]:
    """Reads the insurance folders and analyses only the groups with new or changed files (and upgrades regex-only groups once the model is reachable).
    use_model: None, or an object with available() -> bool and __call__(name, docs, regex_facts) -> facts | None (analysis/insurance.py ModelReader).
    Returns {groups, analysed, unchanged, pending_model, errors, folders}."""
    ensure(conn)
    rep: dict[str, Any] = dict(groups=0, analysed=0, unchanged=0, pending_model=0, errors=[], folders=0)
    known = stored_sigs(conn)
    keep: set[str] = set()
    for fld in folders:
        root = Path(fld)
        if not root.is_dir():
            rep["errors"].append(f"folder not found: {fld}")
            continue
        rep["folders"] += 1
        for g, files in scan_group_files(root).items():
            gkey = f"{root.name}/{g}" if len(folders) > 1 else g
            keep.add(gkey)
            rep["groups"] += 1
            sig = group_sig(files)
            old_sig, old_reader = known.get(gkey, ("", None))
            want_model = use_model is not None and old_reader != "model" and budget > 0 and use_model.available()
            if old_sig == sig and not want_model:
                rep["unchanged"] += 1
                if old_reader != "model":
                    rep["pending_model"] += 1
                continue
            docs = read_group_text(files)
            facts = regex_extract(g, docs, today)
            in_force = None
            rec: dict[str, Any] = dict(name=re.sub(r"^file: ", "", g), reader="regex", **{k: facts[k] for k in ("company", "kind", "policy_no", "start_date", "end_date", "auto_renew", "premium", "interval")})
            if use_model is not None and docs and budget > 0 and use_model.available():
                budget -= 1
                try:
                    got = use_model(g, docs, facts)
                except (OSError, ValueError, RuntimeError, KeyError, TypeError) as e:
                    safenet.swallowed("insurance.model", e)
                    got = None
                if got:
                    known_co = facts["company"] if company_domain(facts["company"]) else None       # a known insurer name from the papers beats the model's wording
                    rec.update({k: v for k, v in got.items() if v not in (None, "", [])})
                    if known_co:
                        rec["company"] = known_co
                    rec["reader"] = "model"
                    in_force = got.get("in_force")
            if rec["reader"] != "model":
                rep["pending_model"] += 1
            newest = newest_date(files)
            age = (today - newest).days if newest else None
            gone = bool(facts["cancelled"] or rec.get("cancelled")) or (in_force is False and (age is None or age > SHAKY_DAYS))
            end, status = settle_dates(rec.get("start_date"), rec.get("end_date"), bool(rec.get("auto_renew")), gone, today)
            if status == "active" and not end and age is not None and age > STALE_DAYS:
                status = "ended"
            rec["end_date"], rec["status"] = end, status
            if g.startswith("file: "):
                rec["name"] = f"{rec.get('company') or ''} {rec.get('kind') or 'insurance'}".strip()
            if not docs:
                rec["summary"] = rec.get("summary") or "No readable text in the files (scans without a text layer)."
            save_group(conn, gkey, str(root), files, sig, rec, now)
            rep["analysed"] += 1
    drop_missing(conn, keep) if rep["folders"] else None
    conn.commit()
    return rep


# ------------------------------------------------------------------ folders added in the dashboard Setup (table insurance_folders)
def list_folders(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure(conn)
    return [dict(id=r[0], path=r[1]) for r in conn.execute("SELECT id, path FROM insurance_folders ORDER BY id")]


def folder_action(conn: sqlite3.Connection, body: dict[str, Any], now: str) -> dict[str, Any]:
    """Setup: {action: add, path} / {action: remove, id}. The folder is only ever read - nothing in it is changed. Returns the new list."""
    ensure(conn)
    act = body.get("action")
    if act == "add":
        path = str(body.get("path") or "").strip()
        if not path or not Path(path).is_dir():
            return dict(ok=False, error="That folder does not exist.")
        conn.execute("INSERT OR IGNORE INTO insurance_folders(path, created) VALUES(?,?)", (path, now))
    elif act == "remove":
        conn.execute("DELETE FROM insurance_folders WHERE id=?", (int(body.get("id") or 0),))
    else:
        return dict(ok=False, error="Unknown action.")
    conn.commit()
    return dict(ok=True, folders=list_folders(conn))


def all_folders(conn: sqlite3.Connection, config_folders: list[Any]) -> list[str]:
    """Folders of config.json (insurance_folders: the installers write them) plus the ones added in Setup; no duplicates, order kept."""
    out: list[str] = []
    for f in [*(config_folders or []), *(d["path"] for d in list_folders(conn))]:
        f = str(f).strip()
        if f and f.lower() not in {o.lower() for o in out}:
            out.append(f)
    return out

"""WealthView database, part 2: sync() scans the watched folders (GLS Umsaetze + Depotbestand, PayPal Download*.CSV, generic CSV folders of cfg["csv_sources"]) READ-ONLY and imports what is new.
Files are recognised by their content (sha256), bookings by a booking key, so overlapping exports and duplicate downloads never create duplicate rows
and running it twice changes nothing."""
from __future__ import annotations
from typing import Any, cast
import hashlib, json, os, re, sqlite3
import datetime as dt
from pathlib import Path

from ...common import parsing, safenet
from ...common.types.accounts import SourceRow
from ...common.types.status import ImportedFile, SyncReport
from . import db_accounts, db_auto, gls_parse, plugins
from .db_common import booking_key, finish_file as _finish_file, link_bookings as _link_bookings
from .plugins.gls_depot import GlsDepotPlugin
from .db_schema import meta_get, meta_set, schema_version, transaction


def sha_of(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _register(conn: sqlite3.Connection, path: str | Path, source: str) -> tuple[int | None, str]:
    """-> (file_id or None, state) with state 'new' | 'unchanged' (same path/size/mtime as before) | 'duplicate' (same content already imported)."""
    st = Path(path).stat()
    p, size, mt = str(path), st.st_size, int(st.st_mtime)
    r = conn.execute("SELECT sha FROM file_seen WHERE path=? AND size=? AND mtime=?", (p, size, mt)).fetchone()
    if r:
        return None, "unchanged"
    sha = sha_of(path)
    conn.execute("INSERT OR REPLACE INTO file_seen(path,size,mtime,sha) VALUES(?,?,?,?)", (p, size, mt, sha))
    if conn.execute("SELECT 1 FROM files WHERE sha=?", (sha,)).fetchone():
        return None, "duplicate"
    cur = conn.execute("INSERT INTO files(source,name,size,sha,imported_at) VALUES(?,?,?,?,?)",
                       (source, Path(path).name, size, sha, dt.datetime.now().isoformat(timespec="seconds")))
    return cur.lastrowid, "new"






def import_gls_file(conn: sqlite3.Connection, path: str | Path, fid: int | None, source: SourceRow | None = None) -> tuple[int, int]:
    rows = plugins.REGISTRY["gls"].parse(str(path))
    fkey = gls_parse.file_name_date(Path(path)).toordinal()
    known = {r[0] for r in conn.execute("SELECT bkey FROM bookings")}
    new = 0
    for i, r in enumerate(rows):
        k = booking_key(r["iban"], r["date"].isoformat(), r["amount"], r["balance"], r["purpose"], r["counterparty"])
        if k not in known:
            new += 1
            known.add(k)
        conn.execute(
            "INSERT INTO bookings(bkey,account,kind,iban,date,counterparty,cp_iban,type,purpose,amount,balance,category,file_id,fkey,ord) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(bkey) DO UPDATE SET fkey=excluded.fkey, ord=excluded.ord, file_id=excluded.file_id "
            "WHERE excluded.fkey > bookings.fkey",
            (k, r["account"], r["kind"], r["iban"], r["date"].isoformat(), r["counterparty"], r["cp_iban"], r["typ"], r["purpose"], r["amount"], r["balance"],
             r["cat"], fid, fkey, i))
    _link_bookings(conn, source, {r["iban"]: (r["account"], r["kind"]) for r in rows})
    dates = [r["date"].isoformat() for r in rows]
    _finish_file(conn, fid, len(rows), new, min(dates) if dates else None, max(dates) if dates else None)
    return len(rows), new


def csv_pseudo_iban(entity: str) -> str:
    """Stable pseudo account id of a generic CSV source: 'CSV-' + the entity label (generic CSVs carry no IBAN; the pipeline groups accounts by iban)."""
    slug = re.sub(r"\W+", "-", entity or "", flags=re.UNICODE).strip("-").upper()
    return "CSV-" + (slug or hashlib.sha1((entity or "").encode("utf-8"), usedforsecurity=False).hexdigest()[:8].upper())


def import_csv_file(conn: sqlite3.Connection, path: str | Path, fid: int | None, source_cfg: dict[str, Any], source: SourceRow | None = None) -> tuple[int, int]:
    """Generic CSV (plugin 'csv') -> bookings. source_cfg = {folder, entity, mapping}; mapping None means a guess from the header (UnsupportedFile when none fits).
    The csv rows have only date, amount, text and counterparty, so: account = the entity label, kind 'giro', iban = csv_pseudo_iban(entity), purpose = text,
    balance None, cp_iban/type/category ''. Without a balance, identical rows of one file (same day, amount, text) would collapse into one key, so the n-th
    repeat inside a file gets '#n' added to the key (an overlapping export that starts in the middle of such a day may count one extra row)."""
    rows = plugins.REGISTRY["csv"].parse(str(path), mapping=source_cfg.get("mapping") or None)
    entity = str(source_cfg.get("entity") or "")
    iban = csv_pseudo_iban(entity)
    fkey = dt.date.fromtimestamp(Path(path).stat().st_mtime).toordinal()
    known = {r[0] for r in conn.execute("SELECT bkey FROM bookings")}
    seen: dict[str, int] = {}
    new = 0
    for i, r in enumerate(rows):
        dstr = r["date"]        # csv_generic returns ISO date strings
        purpose, cp = r.get("text") or "", r.get("counterparty") or ""
        base = booking_key(iban, dstr, r["amount"], None, purpose, cp)
        n = seen[base] = seen.get(base, -1) + 1
        k = base if n == 0 else booking_key(f"{iban}#{n}", dstr, r["amount"], None, purpose, cp)
        if k not in known:
            new += 1
            known.add(k)
        conn.execute(
            "INSERT INTO bookings(bkey,account,kind,iban,date,counterparty,cp_iban,type,purpose,amount,balance,category,file_id,fkey,ord) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(bkey) DO UPDATE SET fkey=excluded.fkey, ord=excluded.ord, file_id=excluded.file_id "
            "WHERE excluded.fkey > bookings.fkey",
            (k, entity, "giro", iban, dstr, cp, "", "", purpose, r["amount"], None, "", fid, fkey, i))
    if rows:
        _link_bookings(conn, source, {iban: (entity, "giro")})
    dates = [r["date"] for r in rows]
    _finish_file(conn, fid, len(rows), new, min(dates) if dates else None, max(dates) if dates else None)
    return len(rows), new


def import_depot_file(conn: sqlite3.Connection, path: str | Path, fid: int | None, source: SourceRow | None = None) -> tuple[int, int]:
    asof, pos, _ = cast("GlsDepotPlugin", plugins.REGISTRY["gls_depot"]).parse_export(str(path))
    if asof is None:
        raise gls_parse.UnsupportedFile("no valid date in the depot export")
    pos = list({p["wkn"]: p for p in pos}.values())        # some exports list every position twice
    if source is not None:
        acc = db_accounts.account_for(conn, source["id"], "depot", "Depot", "depot")
        sql = "INSERT OR REPLACE INTO depot_positions(account_id,asof,wkn,name,qty,price,value,gain,gain_pct,file_id) VALUES(?,?,?,?,?,?,?,?,?,?)"
    else:           # old shape (schema 1) or a database without sources: as before v1.19
        sql = "INSERT OR REPLACE INTO depot_positions(asof,wkn,name,qty,price,value,gain,gain_pct,file_id) VALUES(?,?,?,?,?,?,?,?,?)"
    for p in pos:
        vals = (asof.isoformat(), p["wkn"], p["raw"], p["qty"], p["price"], p["value"], p["gain"], p["gain_pct"], fid)
        conn.execute(sql, vals if source is None else (acc,) + vals)
    _finish_file(conn, fid, len(pos), len(pos), asof.isoformat(), asof.isoformat())
    return len(pos), len(pos)


PP_NEED = plugins.paypal_plugin.NEED


def _paypal_key(r: dict[str, Any], code: str) -> str:
    """stable id of one PayPal row (the export has no unique key of its own)"""
    return hashlib.sha1("|".join([code, r.get("Typ") or "", r.get("Datum") or "", r.get("Uhrzeit") or "", r.get("Brutto") or "",
                                  r.get("Status") or ""]).encode("utf-8"), usedforsecurity=False).hexdigest()


def import_paypal_file(conn: sqlite3.Connection, path: str | Path, fid: int | None, source: SourceRow | None = None) -> tuple[int, int]:
    try:
        rd = plugins.REGISTRY["paypal"].parse(str(path))
    except gls_parse.UnsupportedFile:      # a Download*.csv without the PayPal columns: recorded with a note, not an error
        _finish_file(conn, fid, 0, 0, note="not a PayPal activity export")
        return 0, 0
    known = {r[0] for r in conn.execute("SELECT pkey FROM paypal_tx")}
    n = new = 0
    dates = []
    for r in rd:
        d = parsing.pdate(r.get("Datum"))
        if not d:
            continue
        n += 1
        code = (r.get("Transaktionscode") or "").strip()
        k = _paypal_key(r, code)
        dates.append(d.isoformat())
        if k in known:
            continue
        known.add(k)
        new += 1
        conn.execute("INSERT INTO paypal_tx(pkey,date,time,name,type,status,currency,gross,fee,net,balance,code,subject,file_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (k, d.isoformat(), r.get("Uhrzeit"), r.get("Name"), r.get("Typ"), r.get("Status"), r.get("Währung"),
                      parsing.num(r.get("Brutto")), parsing.num(r.get("Gebühr")), parsing.num(r.get("Netto")), parsing.num(r.get("Guthaben")),
                      code, r.get("Artikelbezeichnung") or r.get("Betreff"), fid))
    if source is not None and n:
        conn.execute("UPDATE paypal_tx SET account_id=? WHERE account_id IS NULL", (db_accounts.account_for(conn, source["id"], "paypal", source["name"], "bank"),))
    _finish_file(conn, fid, n, new, min(dates) if dates else None, max(dates) if dates else None)
    return n, new




LEGACY_IMPORTERS = {"gls": import_gls_file, "gls_depot": import_depot_file, "paypal": import_paypal_file}       # known exports found in an 'auto' folder

MAX_SUBFOLDER_DEPTH = 4      # sub-folder levels read below a source's folder
MAX_SUBFOLDERS = 500         # folders read per source; a larger tree is cut off (in sorted order) so a wrong folder cannot stall the refresh


def _subfolders(root: Path, deep: bool) -> list[Path]:
    """`root` and, with deep, the folders below it (sorted; hidden '.x' folders and links skipped; at most MAX_SUBFOLDER_DEPTH levels)."""
    out, level = [root], [root]
    for _ in range(MAX_SUBFOLDER_DEPTH if deep else 0):
        nxt: list[Path] = []
        for d in level:
            try:
                nxt += sorted(p for p in d.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith("."))
            except OSError as exc:      # unreadable sub-folder: skipped
                safenet.swallowed("db_import._subfolders", exc)
        out += nxt
        level = nxt
        if len(out) >= MAX_SUBFOLDERS or not nxt:
            break
    return out[:MAX_SUBFOLDERS]


def _plain_files(d: Path) -> list[Path]:
    try:
        return sorted(p for p in d.iterdir() if p.is_file())
    except OSError as exc:      # unreadable folder: skipped
        safenet.swallowed("db_import._plain_files", exc)
        return []


def _source_files(src: SourceRow) -> list[tuple[str, Path]]:
    """[(import kind, path)] of one folder source, by its reader: 'gls' = bank booking and depot exports (older booking exports of the folder
    above with options.include_parent), 'paypal' = Download*.csv, 'csv' = every other *.csv. Reader 'auto' (v1.20) = every *.csv / *.txt, read by the automatic reader (db_auto)."""
    root, opts, reader = Path(str(src["folder"])), src["options"], src["reader"]
    out: list[tuple[str, Path]] = []
    folders = _subfolders(root, opts.get("subfolders", True) is not False)
    for d in folders:
        for p in _plain_files(d):
            n = p.name.lower()
            if not n.endswith(".csv") and not (reader == "auto" and n.endswith(".txt")):
                continue
            if reader == "gls" and "umsaetze_" in n:
                out.append(("gls", p))
            elif reader == "gls" and n.startswith("depotbestand_"):
                out.append(("depot", p))
            elif reader == "paypal" and n.startswith("download"):
                out.append(("paypal", p))
            elif reader == "csv" and not _claimed_by_gls_or_paypal(p.name):
                out.append(("csv", p))
            elif reader == "auto":
                out.append(("auto", p))
    if reader == "gls" and opts.get("include_parent") is True:
        out += [("gls", p) for p in _plain_files(root.parent) if p.name.lower().endswith(".csv") and "umsaetze_" in p.name.lower()]
    return out


def _walk_sources(sources: list[SourceRow]) -> tuple[list[tuple[str, Path, SourceRow]], list[SourceRow]]:
    """(files with their owning source, sources whose folder is not there). A file reachable from two sources belongs to the first (lowest id)."""
    entries: list[tuple[str, Path, SourceRow]] = []
    missing: list[SourceRow] = []
    seen: set[str] = set()
    for src in sorted(sources, key=lambda s: s["id"]):
        if not src["active"] or src["source_type"] != "folder" or not src["folder"]:
            continue
        if not os.path.isdir(src["folder"]):
            missing.append(src)
            continue
        for kind, p in _source_files(src):
            if _norm(p) not in seen:
                seen.add(_norm(p))
                entries.append((kind, p, src))
    return entries, missing


def watched_entries(cfg: dict[str, Any], sources: list[SourceRow] | None = None) -> list[tuple[str, Path, SourceRow | None]]:
    """watched_files() with the owning source of each file. sources None = the files come from config.json (owner None): no sources yet, or the old shape."""
    if sources is not None:
        return [(k, p, s) for k, p, s in _walk_sources(sources)[0]]
    return [(k, p, None) for k, p in _config_files(cfg)]


def db_sources(conn: sqlite3.Connection) -> list[SourceRow] | None:
    """The active sources of an upgraded database. None = read the folders of config.json as before v1.19: the old shape (schema 1), or a
    database that has no source at all yet. A database whose sources are all switched off gives [] (nothing is read), never the config folders."""
    if schema_version(conn) < 2 or not conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone():
        return None
    return db_accounts.list_sources(conn)


def _gls_files(gd: Path) -> list[tuple[str, Path]]:
    """GLS booking and depot exports in the DATA folder, plus older booking exports in the folder above it"""
    out, seen = [], set()
    for d in (gd, gd.parent):
        try:
            for p in d.iterdir():
                if not p.is_file() or p in seen:
                    continue
                seen.add(p)
                n = p.name.lower()
                if n.endswith(".csv") and "umsaetze_" in n:
                    out.append(("gls", p))
                elif n.endswith(".csv") and n.startswith("depotbestand_") and d == gd:
                    out.append(("depot", p))
        except OSError as exc:      # unreadable folder: skipped
            safenet.swallowed("db_import._gls_files", exc)
    return out


def _paypal_files(folder: str) -> list[tuple[str, Path]]:
    out = []
    try:
        for p in Path(folder).iterdir():
            if p.is_file() and p.suffix.lower() == ".csv" and p.name.lower().startswith("download"):
                out.append(("paypal", p))
    except OSError as exc:      # unreadable PayPal folder: skipped
        safenet.swallowed("db_import._paypal_files", exc)
    return out


def _claimed_by_gls_or_paypal(name: str) -> bool:
    """the GLS / PayPal file-name rules (see _gls_files, _paypal_files): such a file in a csv folder stays with its own importer"""
    n = name.lower()
    return n.endswith(".csv") and ("umsaetze_" in n or n.startswith("depotbestand_") or n.startswith("download"))


def csv_sources(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """The usable entries of cfg["csv_sources"] ([{folder, entity, mapping}]); anything malformed is ignored."""
    raw = cfg.get("csv_sources")
    return [s for s in raw if isinstance(s, dict) and isinstance(s.get("folder"), str) and s["folder"]] if isinstance(raw, list) else []


def _norm(p: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _csv_files(cfg: dict[str, Any]) -> list[tuple[str, Path, dict[str, Any]]]:
    out, seen = [], set()
    for sc in csv_sources(cfg):
        try:
            for p in Path(sc["folder"]).iterdir():
                if p.is_file() and p.suffix.lower() == ".csv" and not _claimed_by_gls_or_paypal(p.name) and _norm(p) not in seen:
                    seen.add(_norm(p))
                    out.append(("csv", p, sc))
        except OSError as exc:      # unreadable csv folder: skipped
            safenet.swallowed("db_import._csv_files", exc)
    return out


def watched_files(cfg: dict[str, Any], sources: list[SourceRow] | None = None) -> list[tuple[str, Path]]:
    """[(import kind, path)] of the files WealthView imports: from the sources when there are any (v1.19), else from config.json as before."""
    return [(k, p) for k, p, _ in watched_entries(cfg, sources)]


def _config_files(cfg: dict[str, Any]) -> list[tuple[str, Path]]:
    """The pre-v1.19 list. GLS: the DATA folder and the folder above it (older exports). csv: every *.csv of each cfg["csv_sources"] folder
    that is not a GLS / PayPal file by name."""
    out = []
    if cfg.get("gls_dir"):
        out += _gls_files(Path(cfg["gls_dir"]))
    if cfg.get("paypal_dir"):
        out += _paypal_files(cfg["paypal_dir"])
    out += [(s, p) for s, p, _ in _csv_files(cfg)]
    return out


def folder_signature(cfg: dict[str, Any], sources: list[SourceRow] | None = None) -> str:
    """Cheap fingerprint of everything watched: file names, sizes, times, which source owns a file, and which source folders are missing
    (so a folder that comes back, or a new source, changes it, while a folder that stays away does not)."""
    h = hashlib.sha1(usedforsecurity=False)
    for s in (_walk_sources(sources)[1] if sources is not None else []):
        h.update(f"missing|{s['id']}|{s['folder']}\n".encode("utf-8"))
    for src, p, owner in sorted(watched_entries(cfg, sources), key=lambda x: str(x[1])):
        if owner is not None:
            h.update(f"source|{owner['id']}|".encode("utf-8"))
        try:
            st = p.stat()
            h.update(f"{src}|{p}|{st.st_size}|{int(st.st_mtime)}\n".encode("utf-8"))
        except OSError as exc:      # vanished file: left out of the signature
            safenet.swallowed("db_import.signature", exc)
    return h.hexdigest()


def folders_changed(conn: sqlite3.Connection, cfg: dict[str, Any]) -> bool:
    return meta_get(conn, "folder_sig") != folder_signature(cfg, db_sources(conn))


def _mark_skipped(conn: sqlite3.Connection, path: str | Path, src: str, note: str) -> None:
    with transaction(conn):
        fid, state = _register(conn, path, src)
        if fid:
            _finish_file(conn, fid, 0, 0, note="skipped: " + note)


def sync(conn: sqlite3.Connection, cfg: dict[str, Any]) -> SyncReport:
    """Import everything new from the watched folders. Source files are only read. Returns a report dict."""
    rep: SyncReport = dict(at=dt.datetime.now().isoformat(timespec="seconds"), seen=0, unchanged=0, new_files=[], duplicate_files=[], errors=[],
               new_bookings=0, new_paypal=0, new_depot=0, new_crypto=0, questions=0)
    sources = db_sources(conn)
    files = watched_entries(cfg, sources)
    gls = sorted([x for x in files if x[0] == "gls"], key=lambda x: (gls_parse.file_name_date(x[1]), x[1].name), reverse=True)
    order = gls + [x for x in files if x[0] != "gls"]
    csv_cfg = {_norm(p): sc for _, p, sc in _csv_files(cfg)} if sources is None else {}
    rep["errors"] += [f"{s['name']}: folder not found" for s in (_walk_sources(sources)[1] if sources is not None else [])]
    unreadable = False       # True when a file failed for a maybe-temporary reason: then the folder signature is not saved, so the next refresh tries again
    for src, p, owner in order:
        rep["seen"] += 1
        try:
            with transaction(conn):        # one file = one transaction: a failing import leaves nothing half-written
                fid, state = _register(conn, p, src)
                if state == "unchanged":
                    rep["unchanged"] += 1
                    continue
                if state == "duplicate":
                    rep["duplicate_files"].append(p.name)
                    continue
                if owner is not None:
                    conn.execute("UPDATE files SET source_id=? WHERE id=?", (owner["id"], fid))
                if src == "auto":
                    assert owner is not None
                    n, new, kind = db_auto.import_auto_file(conn, p, fid, owner, LEGACY_IMPORTERS)
                    if kind in ("waiting", "skipped"):
                        rep["questions"] += kind == "waiting"
                        continue
                    entry = ImportedFile(name=p.name, source=kind, rows=n, new=new, source_name=owner["name"])
                    rep["new_files"].append(entry)
                    if kind in ("gls", "bank", "card"):
                        rep["new_bookings"] += new
                    elif kind in ("depot", "trades"):
                        rep["new_depot"] += new
                    elif kind == "crypto":
                        rep["new_crypto"] += new
                    else:
                        rep["new_paypal"] += new
                    continue
                if src == "csv":
                    sc = csv_cfg[_norm(p)] if owner is None else {"entity": owner["options"]["entity"] if isinstance(owner["options"].get("entity"), str) else owner["name"], "mapping": owner["options"].get("mapping")}
                    n, new = import_csv_file(conn, p, fid, sc, owner)
                else:
                    importer = {"gls": import_gls_file, "depot": import_depot_file, "paypal": import_paypal_file}[src]
                    n, new = importer(conn, p, fid) if owner is None else importer(conn, p, fid, owner)
                entry = ImportedFile(name=p.name, source=src, rows=n, new=new)
                if owner is not None:
                    entry["source_name"] = owner["name"]
                rep["new_files"].append(entry)
                if src in ("gls", "csv"):       # csv rows are bookings too (new_files[].source tells them apart)
                    rep["new_bookings"] += new
                elif src == "depot":
                    rep["new_depot"] += new
                else:
                    rep["new_paypal"] += new
        except gls_parse.UnsupportedFile as e:     # readable but not a format we understand: remember it so it is not retried (and reported) every time
            _mark_skipped(conn, p, src, str(e))
            rep["errors"].append(f"{p.name}: skipped - {str(e)}")
        except Exception as e:     # broad on purpose: any other error (disk, database, locked file ...) may be temporary: report it, try again next time
            unreadable = True
            safenet.swallowed("db_import.sync", e)
            rep["errors"].append(f"{p.name}: {str(e)}")
    with transaction(conn):
        if not unreadable:
            meta_set(conn, "folder_sig", folder_signature(cfg, sources))
        meta_set(conn, "last_sync", json.dumps(rep))
        if rep["new_files"]:
            meta_set(conn, "last_import", json.dumps(rep))
    return rep

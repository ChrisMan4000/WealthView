"""
WealthView - source loaders (file and network IO): GLS bookings (CSV), the depot export, Coinbase and the Example Fund files.
The pure parsers live in gls_parse.py and the booking analysis in gls_block.py; config, the parse cache and RunContext in common/ (config.py, parse_cache.py, runcontext.py).

Loader contract (the same in safenet.py): every load_*(ctx) reports through ctx.set_status/ctx.add_alert (never module globals)
and returns either the loaded value or None when the source is off/unreadable (load_gls always returns (rows, files)). Loaders
turn expected source problems (setting missing, file missing/unreadable/malformed) into a status line and do not raise.
Parsers (gls_parse.py) are pure and raise ValueError; the loader that calls them converts that into status + None.
Reads the source folders READ-ONLY.
"""
from __future__ import annotations
from typing import Any, Callable, Literal, cast
import csv, json, os, re, shutil, sqlite3, subprocess  # nosec B404 - only runs node on the bundled coinbase_fetch.mjs
import datetime as dt
from collections import defaultdict
from pathlib import Path
from ...common import fileio
from ...common import paths
from ...common import netlog
from ...common import safenet
from ...common.fileio import write_atomic
from ...common.types.bookings import BookingRow
from ...common.types.datajson import ExampleFund
from ...common.types.depot import AssetGroup, CryptoBlock, Depot, DepotMeta, DepotPosition, Holding, ParsedPosition
from . import quotes
from .gls_parse import file_name_date, parse_gls_text, parse_depot, depot_file_date
from ...common.paths import data_path
from ...common.config import setting
from ...common.runcontext import UNCHANGED, RunContext
from ...common.parse_cache import cached_parse
from ...common.parsing import iso, round2, read_text
from ...common.timeutil import now, today

GLS_CACHE_NAME = "gls_rows_v2"      # v2: booking keys renamed (amount, balance, counterparty, account); an old cache entry is simply not used


def _read_gls_files(files: list[Path]) -> dict[str, Any]:
    """Raw parse of the GLS CSVs: rows with ISO date strings (JSON-serialisable) + the unreadable files."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    bad: list[str] = []
    for f in files:
        try:
            text = read_text(f)
        except OSError as e:  # e.g. OneDrive placeholder that cannot be hydrated
            bad.append(f"{f.name}: {e}")
            continue
        try:
            parsed = parse_gls_text(text)
        except (ValueError, csv.Error) as e:  # not a readable GLS export (csv.Error is not a ValueError)
            bad.append(f"{f.name}: {e}")
            continue
        for r in parsed:
            key = (r["iban"], r["date"], r["amount"], r["balance"], r["purpose"][:80], r["counterparty"][:30])
            if key in seen:
                continue
            seen.add(key)
            rows.append(dict(r, date=r["date"].isoformat()))
    return dict(rows=rows, bad=bad)


def load_gls(ctx: RunContext) -> tuple[list[BookingRow], list[Path]]:
    gls_dir = setting("gls_dir")
    if not gls_dir:
        ctx.set_status("gls_files", "off", "gls_dir not set in config.json")
        return [], []
    d = Path(gls_dir)
    files = sorted(d.glob("*Umsaetze_*.csv"), key=lambda p: (file_name_date(p), p.name), reverse=True)
    raw = cached_parse(ctx, GLS_CACHE_NAME, files, _read_gls_files)
    rows = cast("list[BookingRow]", [dict(r, date=dt.date.fromisoformat(r["date"])) for r in raw["rows"]])
    bad: list[str] = raw["bad"]
    rows.sort(key=lambda x: x["date"], reverse=True)  # stable: keeps file order for equal dates
    if bad:
        ctx.set_status("gls_files", "warn", f"{len(bad)} file(s) unreadable or malformed", detail=bad[:3])
    return rows, files


# -------------------------------------------------------------- GLS depot


def _parse_depot_files(files: list[Path]) -> dict[str, Any]:
    """Raw parse of the newest depot export (+ the total/gain of the one before) as JSON-serialisable data."""
    asof, pos, meta = parse_depot(files[0])
    if asof is None:
        raise ValueError("no valid date in the depot export")
    prev = None
    if len(files) > 1:
        try:
            a2, _p2, m2 = parse_depot(files[1])
            prev = dict(asof=iso(a2), meta=m2, file=files[1].name)
        except (OSError, ValueError) as exc:
            safenet.swallowed("loaders.load_depot", exc)
    return dict(asof=iso(asof), pos=pos, meta=meta, prev=prev)


def _depot_position(p: ParsedPosition) -> DepotPosition:
    """one parsed depot line -> the position block, with the class / theme / short name of config.json -> depot_meta"""
    mt = setting("depot_meta", {}).get(p["wkn"], {})
    value = p["value"] or 0.0
    gain = p["gain"] or 0.0
    return dict(
        wkn=p["wkn"], name=mt.get("short") or p["raw"].title(), raw=p["raw"],
        cls=mt.get("cls", "Other"), theme=mt.get("theme", "Other"),
        qty=p["qty"], price=round2(p["price"]), value=round2(value), gain=round2(gain),
        gain_pct=round2(p["gain_pct"]), cost=round2(value - gain) if p["value"] else None,
        no_quote=p["value"] is None,
    )


def _value_by(positions: list[DepotPosition], key: Literal["cls", "theme"]) -> list[AssetGroup]:
    """total value per class or theme ('cls' / 'theme'), biggest first"""
    agg: defaultdict[str, float] = defaultdict(float)
    for x in positions:
        agg[x[key]] += x["value"]
    return [AssetGroup(k=k, v=round2(v)) for k, v in sorted(agg.items(), key=lambda kv: -kv[1])]


def _depot_alerts(ctx: RunContext, out: Depot, asof: dt.date) -> None:
    """status line of the depot source plus the alerts for old prices and for one position that dominates the depot"""
    age = (today() - asof).days
    out["age_days"] = age
    ctx.set_status("depot", "ok" if age <= 7 else "warn", f"as of {asof:%d.%m.%Y} ({age} d old)" + (UNCHANGED if ctx.cache_hits.get("depot") else ""))
    if age > 7:
        ctx.add_alert("warn", f"Depot prices are {age} days old - export a fresh 'Depotbestand' from GLS into the DATA folder.")
    if out["top1"] and out["top1"] > 20:
        top = out["positions"][0]
        ctx.add_alert("info", f"Concentration: {top['name']} is {out['top1']:.0f}% of the depot (top 3 = {out['top3']:.0f}%).")


def load_depot(ctx: RunContext) -> Depot | None:
    gls_dir = setting("gls_dir")
    if not gls_dir:
        ctx.set_status("depot", "off", "gls_dir not set in config.json")
        return None
    d = Path(gls_dir)
    files = sorted(d.glob("Depotbestand_*.csv"), key=depot_file_date, reverse=True)
    if not files:
        ctx.set_status("depot", "off", "no Depotbestand file found")
        return None
    try:
        raw = cached_parse(ctx, "depot", files[:2], _parse_depot_files)
        asof, pos, meta = dt.date.fromisoformat(raw["asof"]), raw["pos"], raw["meta"]
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as e:
        ctx.set_status("depot", "off", f"cannot read {files[0].name}: {e}")
        return None
    out = _build_depot(ctx, pos, meta, asof, files[0].name)
    if raw.get("prev"):
        pv = raw["prev"]
        out["prev"] = dict(asof=pv["asof"], total=round2(pv["meta"].get("total")), gain=round2(pv["meta"].get("gain")), file=pv["file"])
    _depot_alerts(ctx, out, asof)
    return out


def _build_depot(ctx: RunContext, pos: list[ParsedPosition], meta: DepotMeta, asof: dt.date, file: str) -> Depot:
    """the Depot block from parsed positions (a depot file or the database): weights, classes, themes, concentration"""
    positions = [_depot_position(p) for p in pos]
    total = meta.get("total") or sum(x["value"] for x in positions)
    for x in positions:
        x["weight"] = round2(x["value"] / total * 100) if total else 0
    positions.sort(key=lambda x: -x["value"])
    wsorted = sorted([x["value"] / total for x in positions], reverse=True) if total else []
    return Depot(
        asof=asof.isoformat(), file=file, total=round2(total), gain=round2(meta.get("gain")),
        gain_pct=round2(meta.get("gain_pct")), cost=round2(total - (meta.get("gain") or 0)),
        positions=positions,
        classes=_value_by(positions, "cls"),
        themes=_value_by(positions, "theme"),
        top1=round2(wsorted[0] * 100) if wsorted else None,
        top3=round2(sum(wsorted[:3]) * 100) if wsorted else None,
        hhi=int(sum((w * 100) ** 2 for w in wsorted)) if wsorted else None,
    )


_DEPOT_DB_SQL = ("SELECT p.wkn, p.name, p.qty, p.price, p.value, p.gain, p.asof FROM depot_positions p "
                 "JOIN accounts a ON a.id = p.account_id JOIN sources s ON s.id = a.source_id "
                 "WHERE s.active = 1 AND p.asof = (SELECT MAX(q.asof) FROM depot_positions q WHERE q.account_id = p.account_id)")


def load_depot_db(ctx: RunContext, conn: sqlite3.Connection) -> Depot | None:
    """The depot from the database (positions the automatic reader stored): the newest export of every depot of an active source; the
    same security in two depots is added up. None when there are none."""
    rows = conn.execute(_DEPOT_DB_SQL).fetchall()
    if not rows:
        return None
    merged: dict[str, ParsedPosition] = {}
    for wkn, name, qty, price, value, gain, _asof in rows:
        m = merged.get(wkn)
        if m is None:
            merged[wkn] = ParsedPosition(raw=name or wkn, wkn=wkn, qty=qty, price=price, value=value, gain=gain,
                                         gain_pct=None)
        else:
            m["qty"] = (m["qty"] or 0) + (qty or 0)
            m["value"] = (m["value"] or 0) + (value or 0)
            m["gain"] = (m["gain"] or 0) + (gain or 0)
    pos = list(merged.values())
    for m in pos:
        cost = (m["value"] or 0) - (m["gain"] or 0)
        m["gain_pct"] = round(m["gain"] / cost * 100, 2) if m["gain"] is not None and cost > 0 else None
    total = sum(p["value"] or 0 for p in pos)
    gain = sum(p["gain"] or 0 for p in pos)
    asof = dt.date.fromisoformat(max(r[6] for r in rows)[:10])
    cost = total - gain
    out = _build_depot(ctx, pos, DepotMeta(total=total, gain=gain, gain_pct=round(gain / cost * 100, 2) if cost > 0 else None), asof, "database")
    _depot_alerts(ctx, out, asof)
    return out


def _cb_tx(r: Any) -> dict[str, Any]:
    """one stored crypto row -> the flattened Coinbase transaction the cost basis reads (priced only when it was paid in EUR)"""
    sign = 1 if r["side"] == "buy" else -1
    total = r["total"] if r["total"] is not None else (r["price"] or 0) * r["qty"]
    return dict(type=r["side"], date=r["date"], qty=sign * abs(r["qty"]), native=sign * abs(total) if total else None, native_cur=r["currency"] or "EUR")


def _spot_eur(asset: str) -> float | None:
    """latest EUR price of a coin from the public price service (None when it cannot be had)"""
    try:
        meta, _, _ = quotes.ychart(f"{asset}-EUR")
        p = meta.get("regularMarketPrice")
        return float(p) if p is not None else None
    except quotes.MARKET_ERRORS as e:
        safenet.swallowed("crypto price", e)
        return None


def load_crypto_db(ctx: RunContext, conn: sqlite3.Connection, price_of: Callable[[str], float | None] = _spot_eur) -> CryptoBlock | None:
    """The crypto block from the database (buys and sells the automatic reader stored for active sources): balance = buys - sells per coin,
    transactions kept for the FIFO cost. None when nothing is held."""
    rows = conn.execute("SELECT t.asset, t.side, t.qty, t.price, t.total, t.currency, t.date FROM crypto_tx t JOIN accounts a ON a.id = t.account_id "
                        "JOIN sources s ON s.id = a.source_id WHERE s.active = 1 ORDER BY t.date, t.ckey").fetchall()
    if not rows:
        return None
    held: dict[str, float] = defaultdict(float)
    txs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        asset = r[0]
        held[asset] += (1 if r[1] == "buy" else -1) * abs(r[2])
        txs[asset].append(_cb_tx(dict(side=r[1], qty=r[2], price=r[3], total=r[4], currency=r[5], date=r[6])))
    holdings: list[Holding] = []
    for asset, amount in sorted(held.items()):
        if amount <= 1e-9:
            continue
        price = price_of(asset)
        holdings.append(Holding(currency=asset, amount=round(amount, 10), price=price or 0.0, eur=round2(amount * price) if price else 0.0))
    if not holdings:
        return None
    holdings.sort(key=lambda h: -h["eur"])
    ctx.set_status("coinbase", "ok", f"{len(holdings)} assets, from your files")
    return CryptoBlock(ok=True, holdings=holdings, total_eur=round2(sum(h["eur"] for h in holdings)), txs=dict(txs), trades_status="ok",
                       asof=now().isoformat(timespec="seconds"), source="database")


# ---------------------------------------------------------------- Coinbase
def load_coinbase(ctx: RunContext) -> CryptoBlock | None:
    cache = data_path("coinbase_cache.json")
    node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    if not (os.environ.get("COINBASE_KEY_NAME") and os.environ.get("COINBASE_KEY_SECRET")):
        ctx.set_status("coinbase", "off", "API key not configured (user environment variables)")
        return fileio.load_json_cache(cache, {}) or None
    res: Any
    try:
        netlog.log("api.coinbase.com", "Coinbase")      # never raises
        p = subprocess.run([node, str(paths.BASE / "coinbase_fetch.mjs")], capture_output=True, text=True,  # nosec B603 - fixed argument list, no shell
                           timeout=60, cwd=str(paths.BASE))
        res = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {"ok": False, "error": p.stderr}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:     # node missing / timed out / printed no JSON
        res = {"ok": False, "error": str(e)}
    if res.get("ok"):
        res["asof"] = now().isoformat(timespec="seconds")
        write_atomic(cache, json.dumps(res, ensure_ascii=False))
        ctx.set_status("coinbase", "ok", f"{len(res.get('holdings', []))} assets, live")
        return res
    safenet.log.warning("Coinbase API error: %s", res.get("error"))     # full text goes to the log ...
    ctx.set_status("coinbase", "warn", "API error: " + str(res.get("error"))[:140])   # ... the status line stays short: the error can be a multi-line node stack trace
    ctx.add_alert("warn", "Coinbase API call failed - showing last known balances." if fileio.load_json_cache(cache, {}) else "Coinbase API call failed.")
    old: CryptoBlock = fileio.load_json_cache(cache, {})      # a missing or corrupt cache just means "no last known balances"
    if old:
        old["stale"] = True
        return old
    return None


# --------------------------------------------------------------- Example Fund
def _scan_wf_reports(pdfs: list[Path]) -> list[Any] | None:
    """Newest quarterly report among the PDFs: [[year, quarter], file name] or None (looks at the file names only)."""
    latest: list[Any] | None = None
    for p in pdfs:
        m = re.search(r"Q([1-4])\s*(20\d\d)", p.name)
        if m and ("Presentation" in p.name or "Reporting" in p.name):
            key = [int(m.group(2)), int(m.group(1))]
            if latest is None or key > latest[0]:
                latest = [key, p.name]
    return latest


def load_examplefund(ctx: RunContext) -> ExampleFund | None:
    f = paths.BASE / "examplefund.json"
    if not f.exists():
        ctx.set_status("examplefund", "off", "examplefund.json missing")
        return None
    try:
        wf: ExampleFund = cached_parse(ctx, "examplefund_json", [f], lambda ps: json.loads(ps[0].read_text("utf-8")))
        pers, fund = wf["personal"], wf["fund"]
        ratio = pers["nav"] / fund["nav"]
        pers["ownership_pct"] = round(ratio * 100, 4)
        pers["dist_est"] = round(fund["distributions"] * pers["paid_in"] / fund["paid_in"], 0)
        pers["tvpi_est"] = round((pers["nav"] + pers["dist_est"]) / pers["paid_in"], 3)
        for c in wf["companies"]:
            c["look_through"] = round(c["fair_value"] * ratio, 0)
        cur = (wf["report_year"], wf["report_q"])
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:     # loader contract: report it in the status line instead of raising
        safenet.swallowed("loaders.load_examplefund", exc)
        ctx.set_status("examplefund", "warn", f"cannot read examplefund.json: {exc}")
        return None
    # newer quarterly report available? (needs the examplefund_dir setting; without it this check is skipped)
    latest = None
    wf_dir = setting("examplefund_dir")
    if wf_dir:
        d = Path(wf_dir) / "Fund I Reporting"
        try:
            raw_latest = cached_parse(ctx, "examplefund_reports", sorted(d.glob("*.pdf")), _scan_wf_reports)
            latest = ((raw_latest[0][0], raw_latest[0][1]), raw_latest[1]) if raw_latest else None
        except (OSError, ValueError, IndexError, TypeError) as exc:
            safenet.swallowed("loaders.load_examplefund", exc)
    wf["newest_report_file"] = latest[1] if latest else None
    title = setting("fund_title")      # your own display name for the fund (config.json -> fund_title); without it the page says "Example Fund I"
    if isinstance(title, str) and title.strip():
        wf["title"] = title.strip()[:60]
    if latest and latest[0] > cur:
        wf["update_available"] = True
        ctx.add_alert("warn", f"New Example Fund report found ({latest[1]}) - ask Claude to update examplefund.json.")
        ctx.set_status("examplefund", "warn", f"newer report available: Q{latest[0][1]} {latest[0][0]}")
    else:
        ctx.set_status("examplefund", "ok", f"Q{wf['report_q']} {wf['report_year']} report"
                       + (UNCHANGED if ctx.cache_hits.get("examplefund_json") and ctx.cache_hits.get("examplefund_reports") else ""))
    return wf

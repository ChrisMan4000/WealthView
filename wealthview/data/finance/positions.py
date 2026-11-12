"""Depot and crypto positions: Yahoo symbol resolution, live-price enrichment, cost basis and the income estimate."""
from __future__ import annotations
from typing import Any
import json, re
import datetime as dt

from ...common import config
from ...common import fileio
from ...common import safenet
from . import lots
from ...common.paths import data_path
from ...common.runcontext import RunContext
from ...common.parsing import round2
from ...common.timeutil import today
from ...common.fileio import write_atomic
from ...common.timeutil import axis
from ...common.types.datajson import IncomeEstimate, IncomeItem
from ...common.types.depot import CryptoBlock, Depot, DepotPosition, Holding, UnknownLot
from ..ingest.quotes import MARKET_ERRORS, search_syms, try_symbol, ydiv, to_eur, monthly_closes, align

# ------------------------------------------------------ live quotes (stocks)
NAME_STRIP = re.compile(r"\(.*?\)|adr|etf|ucits|\bag\b", re.I)


def _symbol_candidates(p: DepotPosition, entry: dict[str, Any], cands: dict[str, Any]) -> tuple[list[str], bool]:
    """symbols to try for one position: the cached one, the configured ones, else a Yahoo name search (unless it failed within a week).
    Returns (symbols, searched); searched is True only when a real name search was made."""
    order = []
    if entry.get("sym"):
        order.append(entry["sym"])
    order += cands.get(p["wkn"], [])
    retry_ok = True
    if entry.get("fail") and not order:
        try:
            retry_ok = (today() - dt.date.fromisoformat(entry["fail"])).days >= 7
        except (ValueError, TypeError) as exc:
            safenet.swallowed("positions.resolve_positions", exc)
    searched = False
    if retry_ok and not order:
        q = NAME_STRIP.sub("", p["name"]).strip()
        order += search_syms(q)[:3]
        searched = True
    return order, searched


def _first_valid_symbol(order: list[str], snap: float | None, tolerance: float) -> dict[str, Any] | None:
    """the first candidate whose price matches the export price, else None"""
    for s in dict.fromkeys(order):
        try:
            got = try_symbol(s, snap, tolerance)
        except MARKET_ERRORS as exc:       # one bad symbol lookup (network or an unexpected answer shape) must not stop the whole refresh
            safenet.swallowed("positions.resolve_positions", exc)
            got = None
        if got:
            return got
    return None


def resolve_positions(positions: list[DepotPosition], depot_age: int = 0) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Find a Yahoo symbol per position (validated against the depot export price). Cached in symbols.json."""
    sym_file = data_path("symbols.json")
    cache = fileio.load_json_cache(sym_file, {})
    cands = config.setting("symbol_candidates", {})
    live = {}
    tolerance = min(0.35, 0.07 + 0.012 * max(0, depot_age))      # the older the export, the further live prices may have moved
    for p in positions:
        w = p["wkn"]
        entry = cache.get(w, {})
        order, searched = _symbol_candidates(p, entry, cands)
        got = _first_valid_symbol(order, p["price"], tolerance)
        if got:
            cache[w] = dict(sym=got["sym"], cur=got["cur"])
            live[w] = got
        elif searched:
            cache[w] = dict(fail=today().isoformat())      # a name search found nothing: wait a week before searching again
        # otherwise keep the old entry: a cached symbol survives a failed lookup, and a skipped search keeps its old 'fail' date
    try:
        write_atomic(sym_file, json.dumps(cache, indent=1))
    except OSError as exc:
        safenet.swallowed("positions.resolve_positions", exc)
    return live, cache


def depot_totals(depot: Depot) -> None:
    """Recomputes (in place) total, gain, cost, gain_pct, weights and the value-sorted order of a depot from its positions."""
    pos = depot["positions"]
    tot = sum(p["value"] for p in pos)
    depot["total"] = round2(tot)
    for p in pos:
        p["weight"] = round2(p["value"] / tot * 100) if tot else 0
    gain = round2(sum(p["gain"] or 0 for p in pos))
    cost = round2(tot - gain)
    depot["gain"] = gain
    depot["cost"] = cost
    depot["gain_pct"] = round2(gain / cost * 100) if cost else None
    pos.sort(key=lambda x: -x["value"])


def _add_history(p: DepotPosition, g: dict[str, Any] | None) -> None:
    """monthly price history of one position (p["hist"]); a flat line at the snapshot price when there is none"""
    p["hist"] = None
    if g:
        try:
            p["hist"] = align(monthly_closes(g["sym"], g["cur"]))
        except MARKET_ERRORS as exc:       # one symbol's history must not stop the refresh (flat line is used)
            safenet.swallowed("positions.add_history", exc)
            p["hist"] = None
    if p["hist"] is None and p["price"]:  # no history: flat line at the snapshot price
        p["hist"] = [p["price"]] * len(axis())


def _live_valuation(p: DepotPosition, g: dict[str, Any]) -> None:
    """value / gain of one position at the live price (the snapshot value is kept in value_snapshot)"""
    val = p["qty"] * g["price_eur"]
    cost = p["cost"]
    p["value_snapshot"] = p["value"]
    p["value"] = round2(val)
    if cost:
        p["gain"] = round2(val - cost)
        p["gain_pct"] = round2((val / cost - 1) * 100)


def enrich_depot(ctx: RunContext, depot: Depot) -> None:
    """Adds live quotes, price history and live values to the depot (in place)."""
    try:
        live, cache = resolve_positions(depot["positions"], depot.get("age_days") or 0)
    except Exception as e:      # broad on purpose: quote lookup is optional, the refresh continues with snapshot prices
        ctx.set_status("quotes", "warn", f"Yahoo Finance unreachable: {str(e)}")
        live, cache = {}, {}
    n_live = 0
    for p in depot["positions"]:
        g = live.get(p["wkn"])
        p["sym"] = cache.get(p["wkn"], {}).get("sym")
        p["live"] = bool(g)
        if g:
            n_live += 1
            p["price_live"] = round2(g["price_eur"])
            p["quote_t"] = g.get("t")
        _add_history(p, g)
        if g and p["qty"]:
            _live_valuation(p, g)
    depot["total_snapshot"] = depot["total"]
    depot_totals(depot)
    depot["n_live"] = n_live
    depot["n_total"] = len(depot["positions"])
    ctx.set_status("quotes", "ok" if n_live else "warn", f"{n_live}/{len(depot['positions'])} positions live", live=n_live > 0)


def enrich_crypto(cb: CryptoBlock) -> None:
    """Adds the monthly price history to every holding (in place)."""
    for h in cb.get("holdings", []):
        try:
            h["hist"] = align(monthly_closes(f"{h['currency']}-EUR", "EUR"))
        except MARKET_ERRORS as exc:           # one coin's history must not stop the refresh
            safenet.swallowed("positions.enrich_crypto", exc)
            h["hist"] = None


def _apply_holding_cost(cb: CryptoBlock, h: Holding) -> tuple[float, float] | None:
    """FIFO cost basis of one holding written into h; returns (cost, gain) when the cost is known, else None"""
    trades = lots.trades_from_cb_transactions((cb.get("txs") or {}).get(h["currency"], []))
    res = lots.fifo_lots(trades)
    open_lots = res["open"]
    open_lots = lots.trim_to_balance(open_lots, h["amount"])
    missing = h["amount"] - sum(l["qty"] for l in open_lots)
    if missing > 1e-9:
        open_lots = open_lots + [UnknownLot(date="", qty=missing, price=None, cost_known=False)]
    s = lots.cost_summary(open_lots, h.get("price") or 0.0)
    h["trades"], h["lots"] = trades, open_lots
    h["cost_known_share"], h["first_buy"] = s["cost_known_share"], s["first_buy"]
    cost, gain, avg = s["cost"], s["gain"], s["avg_price"]
    if cost is None or gain is None or avg is None:      # when the cost is known, gain and avg_price are set as well
        return None
    cost, gain = round(cost, 2), round(gain, 2)
    h["cost"], h["gain"], h["avg_price"] = cost, gain, round(avg, 4)
    h["gain_pct"] = round(s["gain_pct"], 2) if s["gain_pct"] is not None else None      # None when the cost is 0
    return cost, gain


def enrich_crypto_cost(cb: CryptoBlock) -> None:
    """Cost basis per holding from the Coinbase transactions (FIFO), written into cb in place. With trades_status != "ok" every cost
    field is None (never 0). A balance larger than the tracked lots is added as a cost-unknown lot."""
    status = cb.get("trades_status") or "none"
    cb["trades_status"] = status
    tot_cost = tot_gain = 0.0
    any_known = False
    for h in cb.get("holdings", []):
        for k in ("cost", "gain", "gain_pct", "first_buy", "avg_price", "cost_known_share", "lots", "trades"):
            h[k] = None
        if status != "ok" or h["currency"] in lots.FIAT:
            continue
        known = _apply_holding_cost(cb, h)
        if known:
            tot_cost += known[0]
            tot_gain += known[1]
            any_known = True
    cb["cost"] = round(tot_cost, 2) if any_known else None
    cb["gain"] = round(tot_gain, 2) if any_known else None
    cb["gain_pct"] = round(tot_gain / tot_cost * 100.0, 2) if any_known and tot_cost > 0 else None


# ------------------------------------------------- portfolio income estimate
def income_estimate(depot: Depot | None, tages_balance: float | None) -> IncomeEstimate:
    out = IncomeEstimate(items=[], covered=0, total_positions=0)
    yearly = 0.0
    if depot:
        out["total_positions"] = len(depot["positions"])
        for p in depot["positions"]:
            qty, sym = p["qty"], p.get("sym")
            if not (sym and qty):
                continue
            try:
                per_share, cur = ydiv(sym)
                eur = to_eur(per_share, cur) * qty if per_share else 0.0      # the FX lookup can fail too (non-EUR dividend)
            except (*safenet.NET_ERRORS, KeyError, IndexError, TypeError, ZeroDivisionError) as exc:
                safenet.swallowed("positions.income_estimate", exc)
                continue
            out["covered"] += 1
            if eur > 0:
                out["items"].append(IncomeItem(n=p["name"], wkn=p["wkn"], v=round2(eur)))
                yearly += eur
    cash_rate = float(config.setting("income", {}).get("cash_rate_pct", 1.0)) / 100.0
    cash_i = max(0.0, tages_balance or 0) * cash_rate
    if cash_i:
        out["items"].append(IncomeItem(n="Savings account interest (assumed %.1f %%)" % (cash_rate * 100), wkn="", v=round2(cash_i)))
    yearly += cash_i
    out["items"].sort(key=lambda x: -x["v"])
    out["yearly"], out["monthly"] = round2(yearly), round2(yearly / 12)
    out["note"] = ("Gross, before tax. From dividends paid over the last 12 months per share x today's holdings (positions with live quotes only); funds that reinvest and crypto pay nothing.")
    return out

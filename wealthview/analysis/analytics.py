"""
WealthView analytics - the measures professional wealth managers use, as small pure functions
(no network, no files). build_analytics() (further down in this file) assembles them for data.json.
Everything returns None where the data is too short or undefined: the UI then shows "n/a".
"""
from __future__ import annotations
from typing import Any
from collections.abc import Mapping, Sequence
import datetime as dt
import math
from ..common import safenet
from ..data.finance.categories import sector_key
from ..common.config import DEFAULTS
from ..data.finance import lots as _lots
from ..common.types.datajson import AnalyticsResult
from ..common.types.depot import DepotPosition, FifoResult, LotTrade
from ..data.finance.lots import EPS      # spread below this is float noise, i.e. a constant series

HHI_SCALE = 10000.0    # Herfindahl index is reported on the 0..10000 scale
MIN_RETURNS = 12      # fewer observations than this: risk statistics are not meaningful


def _mean(v: list[float]) -> float:
    return sum(v) / len(v)


def _stdev(v: list[float]) -> float | None:
    """sample standard deviation"""
    if len(v) < 2:
        return None
    m = _mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


# ------------------------------------------------------------------ returns
def xirr(flows: list[tuple[str, float]]) -> float | None:
    """Money-weighted annual return from dated flows [(ISO date, EUR)]: investments negative, the
    final value positive; 365-day year. None when there is no sign change or no solution."""
    pts = []
    for d, a in flows or []:
        try:
            pts.append((dt.date.fromisoformat(str(d)[:10]), float(a)))
        except (ValueError, TypeError) as exc:      # a malformed flow row is skipped
            safenet.swallowed("analytics.xirr", exc)
    if len(pts) < 2 or not any(a < 0 for _, a in pts) or not any(a > 0 for _, a in pts):
        return None
    t0 = min(d for d, _ in pts)

    def f(r: float) -> float:
        return sum(a / (1 + r) ** ((d - t0).days / 365.0) for d, a in pts)

    lo, hi = -0.999, 10.0
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = f(mid)
        if flo * fm <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


# ------------------------------------------------------------------ risk
def volatility(returns: list[float | None], periods_per_year: float) -> float | None:
    r = [x for x in returns if x is not None]
    if len(r) < MIN_RETURNS:
        return None
    sd = _stdev(r)
    if sd is None:
        return None
    return sd * math.sqrt(periods_per_year)


def max_drawdown(values: Sequence[float | None]) -> tuple[float, int, int] | None:
    """(worst peak-to-trough fraction <= 0, index of the peak, index of the trough)"""
    v = [x for x in values if x is not None]
    if len(v) < 2:
        return None
    peak_i, worst, w_peak, w_trough = 0, 0.0, 0, 0
    for i, x in enumerate(v):
        if x > v[peak_i]:
            peak_i = i
        if v[peak_i] > 0:
            dd = x / v[peak_i] - 1.0
            if dd < worst:
                worst, w_peak, w_trough = dd, peak_i, i
    return (worst, w_peak, w_trough)


def sharpe(returns: list[float | None], rf_annual: float, periods_per_year: float) -> float | None:
    r = [x for x in returns if x is not None]
    if len(r) < MIN_RETURNS:
        return None
    sd = _stdev(r)
    if sd is None or sd < EPS:
        return None
    return (_mean(r) - rf_annual / periods_per_year) / sd * math.sqrt(periods_per_year)


def sortino(returns: list[float | None], rf_annual: float, periods_per_year: float) -> float | None:
    r = [x for x in returns if x is not None]
    if len(r) < MIN_RETURNS:
        return None
    target = rf_annual / periods_per_year
    down = [min(0.0, x - target) ** 2 for x in r]
    dd = math.sqrt(sum(down) / len(r))
    if dd < EPS:
        return None
    return (_mean(r) - target) / dd * math.sqrt(periods_per_year)


def _pearson(a: list[float | None], b: list[float | None]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < MIN_RETURNS:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = _mean(xs), _mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx < EPS or sy < EPS:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / (sx * sy)


def correlation_matrix(series: dict[str, list[float | None]]) -> dict[str, dict[str, float | None]]:
    """{name: {name: pearson | None}} on the points where both series have a value (>= 12 needed)"""
    names = list(series)
    return {a: {b: _pearson(series[a], series[b]) for b in names} for a in names}


# ------------------------------------------------------------------ exposure, stress, allocation
def effective_n(weights: list[float | None]) -> float:
    """effective number of positions = 1 / sum(w^2) on weights normalised to 1"""
    w = [x for x in weights if x and x > 0]
    if not w:
        return 0.0
    s = sum(w)
    return 1.0 / sum((x / s) ** 2 for x in w)


def stress(values: dict[str, float], shocks: dict[str, float]) -> dict[str, Any]:
    by = {k: round(v * shocks.get(k, 0.0), 2) for k, v in values.items()}
    loss = round(sum(by.values()), 2)
    gross = sum(values.values())
    return {"loss_eur": loss, "pct_of_gross": (loss / gross) if gross else None, "by_class": by}


def drift(values: dict[str, float], targets: dict[str, Any]) -> dict[str, Any]:
    """Actual share of gross per asset class against target and band (targets in %)."""
    total = sum(v for v in values.values() if v)
    if total <= 0:
        return {}
    out = {}
    for k, v in values.items():
        t = targets.get(k)
        if not t:
            continue
        pct = v / total * 100.0
        status = "under" if pct < t["low"] else "over" if pct > t["high"] else "ok"
        out[k] = {"pct": pct, "target": t["target"], "low": t["low"], "high": t["high"], "status": status,
                  "diff_pp": pct - t["target"]}
    return out


def deflate(values: list[float | None], cpi: list[float]) -> list[float | None] | None:
    """Express historical values in today's money: v * cpi[-1] / cpi[i]"""
    if not values or len(values) != len(cpi):
        return None
    return [None if v is None or c in (None, 0) else v * cpi[-1] / c for v, c in zip(values, cpi)]


# ================================================================== assembly for data.json
CLASSES = ["Real estate", "Securities", "Private equity", "Cash", "Crypto"]


def _cash_total(d: Mapping[str, Any]) -> float:
    t = d.get("totals") or {}
    return sum((t.get(k) or 0) for k in ("giro", "tages", "card", "shares", "paypal"))


def _private_equity_value(d: Mapping[str, Any]) -> float:
    return (((d.get("examplefund") or {}).get("personal") or {}).get("nav") or 0) + ((d.get("wiwin") or {}).get("invested") or 0)


def class_values(d: Mapping[str, Any]) -> dict[str, float]:
    """current EUR value per asset class - the same definition as the dashboard (wv.js classValues)"""
    return {
        "Real estate": (d.get("apartment") or {}).get("value_used") or 0,
        "Securities": sum(p["value"] for p in (d.get("depot") or {}).get("positions", [])),
        "Private equity": _private_equity_value(d),
        "Cash": _cash_total(d),
        "Crypto": sum(h["amount"] * (h.get("price") or 0) for h in (d.get("crypto") or {}).get("holdings", [])),
    }


def monthly_returns(series: list[float | None]) -> list[float | None]:
    """month-on-month returns of a series (None where a value is missing); one shorter than the series"""
    out = []
    for a, b in zip(series, series[1:]):
        out.append(b / a - 1.0 if a not in (None, 0) and b is not None and a > 0 else None)
    return out


def _first(series: list[float | None] | None) -> int | None:
    for i, v in enumerate(series or []):
        if v is not None:
            return i
    return None


def _risk_block(series: list[float | None], rf: float) -> dict[str, Any]:
    i0 = _first(series)
    if i0 is None:
        return {"vol": None, "max_dd": None, "sharpe": None, "sortino": None, "months": 0, "dd_series": None}
    s = series[i0:]
    r = monthly_returns(s)
    n = sum(1 for x in r if x is not None)
    if n < MIN_RETURNS:
        return {"vol": None, "max_dd": None, "sharpe": None, "sortino": None, "months": n, "dd_series": None}
    vals = [x for x in s if x is not None]
    dd = max_drawdown(vals)
    peak = 0.0
    dds: list[float | None] = []
    for v in s:
        if v is None:
            dds.append(None)
            continue
        peak = max(peak, v)
        dds.append(v / peak - 1.0 if peak > 0 else 0.0)
    return {"vol": volatility(r, 12), "max_dd": dd[0] if dd else None, "sharpe": sharpe(r, rf, 12),
            "sortino": sortino(r, rf, 12), "months": n, "dd_series": dds}


def _initial_qty(p: DepotPosition) -> float:
    """quantity held before the first known trade (today's quantity, undoing the later buys and sells)"""
    tr = p.get("trades") or []
    return (p["qty"] or 0) - sum(t["qty"] for t in tr if t["side"] == "buy") + sum(t["qty"] for t in tr if t["side"] == "sell")


def _start_flow(p: DepotPosition, start: str, idx: int, n_axis: int) -> tuple[float | None, bool]:
    """(flow, skipped) for the holdings of one position at the start date: the money that was 'invested' then, or no flow
    when nothing was held. skipped is True when something was held but the price history has no price for that month."""
    q0 = _initial_qty(p)
    if q0 <= 1e-9:
        return None, False
    h = (p.get("hist") or [None] * n_axis)
    px = h[idx] if idx < len(h) else None
    if px is None:
        return None, True
    return -q0 * px, False


def _securities_flows(d: Mapping[str, Any], today: str) -> tuple[list[tuple[str, float]] | None, int]:
    """Dated flows for XIRR since the first known trade: holdings at that date (back-cast from today's quantities and
    the monthly price history), every later buy/sell, and today's value. None when there is no trade history."""
    dep = d.get("depot") or {}
    start, axis = dep.get("trades_from"), d.get("axis") or []
    if not start or start[:7] not in axis:
        return None, 0
    idx, flows, skipped = axis.index(start[:7]), [], 0
    for p in dep.get("positions", []):
        flow, was_skipped = _start_flow(p, start, idx, len(axis))
        if was_skipped:
            skipped += 1
        elif flow is not None:
            flows.append((start, flow))
        for t in p.get("trades") or []:
            flows.append((t["d"], -t["amount"] if t["side"] == "buy" else t["amount"]))
    total = sum(p["value"] for p in dep.get("positions", []))
    flows.append((today, total))
    return flows, skipped


def _position_sales(p: DepotPosition, start: str | None) -> FifoResult | None:
    """FIFO result (realised sales) of one position, or None when it has no sale"""
    tr = p.get("trades") or []
    if not any(t["side"] == "sell" for t in tr):
        return None
    q0 = _initial_qty(p)
    trades: list[LotTrade] = [{"date": t["d"], "side": t["side"], "qty": t["qty"], "price": t["price"], "fee": 0.0} for t in tr]
    if q0 > 1e-9 and start:
        trades.append({"date": start, "side": "in", "qty": q0, "price": None, "fee": 0.0})   # pre-history lots: cost unknown
    return _lots.fifo_lots(sorted(trades, key=lambda x: (x["date"], x["side"] != "in")))


def _tax(d: Mapping[str, Any], today: str, cfg: dict[str, Any]) -> dict[str, Any]:
    dep, year = d.get("depot") or {}, int(today[:4])
    realised, unknown, start = [], 0, dep.get("trades_from")
    for p in dep.get("positions", []):
        res = _position_sales(p, start)
        if res is None:
            continue
        for r in res["realised"]:
            if r["gain"] is None:
                unknown += 1
            realised.append(r)
    by_year = _lots.realised_by_year(realised)
    allow = _lots.allowance_use(by_year.get(year, 0.0), float((cfg.get("tax") or {}).get("allowance_eur", DEFAULTS["tax"]["allowance_eur"])))
    allow["year"] = year
    return {"realised_by_year": by_year, "allowance": allow, "unknown_cost_sales": unknown,
            "note": "Only positions you still hold and only sales since the first trade in your GLS export; sales from older lots have no known cost.",
            "basis": "estimate"}


def _add_weights(out: dict[str, Any], pr: dict[str, Any], w: float) -> None:
    """adds one position's weight w to the country / currency / sector tables and the coverage figures"""
    for key, field in (("by_country", "country"), ("by_currency", "currency")):
        if pr.get(field):
            out[key][pr[field]] = out[key].get(pr[field], 0.0) + w
            out["coverage"][field] += w
    sw = pr.get("sector_weights") or {}
    if sw:
        for k, x in sw.items():
            out["by_sector"][k] = out["by_sector"].get(k, 0.0) + w * x
        out["coverage"]["sector"] += w * min(1.0, sum(sw.values()))
    elif pr.get("sector"):
        k = sector_key(pr["sector"])
        out["by_sector"][k] = out["by_sector"].get(k, 0.0) + w
        out["coverage"]["sector"] += w


def _add_lookthrough(look: dict[Any, dict[str, Any]], pr: dict[str, Any], w: float) -> None:
    """add the top holdings of one fund (weighted with the fund's share w of the depot) to the look-through table"""
    for h in pr.get("top_holdings") or []:
        e = look.setdefault(h.get("name") or h.get("symbol"), {"name": h.get("name") or h.get("symbol"), "symbol": h.get("symbol"), "weight": 0.0})
        e["weight"] += w * h["weight"]


def aggregate_exposure(positions: list[DepotPosition], profiles: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Weights by country / sector / currency, look-through of fund holdings and the weighted fund cost (TER), from
    Yahoo profiles keyed by WKN. Weights are shares of ALL securities; coverage says how much of the portfolio had data."""
    total = sum(p["value"] for p in positions)
    out: dict[str, Any] = {"by_country": {}, "by_sector": {}, "by_currency": {}, "lookthrough": [], "ter_pct": None, "ter_eur": None,
           "coverage": {"country": 0.0, "sector": 0.0, "currency": 0.0, "ter": 0.0}}
    if not total or not profiles:
        return out
    ter_val = ter_w = 0.0
    look: dict[Any, dict[str, Any]] = {}
    for p in positions:
        pr = profiles.get(p.get("wkn")) or {}
        w = p["value"] / total
        _add_weights(out, pr, w)
        _add_lookthrough(look, pr, w)
        if pr.get("ter") is not None:
            ter_val += pr["ter"] * w
            ter_w += w
    out["coverage"]["ter"] = ter_w
    out["lookthrough"] = sorted(look.values(), key=lambda x: -x["weight"])[:10]
    if ter_w > 0:
        out["ter_pct"] = ter_val / ter_w
        out["ter_eur"] = out["ter_pct"] / 100.0 * ter_w * total
    return out


def parse_hicp(js: dict[str, Any], axis: list[str]) -> list[float] | None:
    """Eurostat JSON-stat (prc_hicp_midx) -> index values aligned to the month axis, gaps carried forward"""
    try:
        pos = js["dimension"]["time"]["category"]["index"]
        val = js["value"]
    except (KeyError, TypeError) as exc:
        safenet.swallowed("analytics.parse_hicp", exc)
        return None
    known = {m: val[str(i)] for m, i in pos.items() if str(i) in val and val[str(i)] is not None}
    if not known:
        return None
    first = known[min(known)]
    out, last = [], None
    for m in axis:
        last = known.get(m, last)
        out.append(last if last is not None else first)
    return out


def _total_return(series: list[float | None], i0: int | None) -> float | None:
    """last value of the series over its value at index i0, minus 1 (None when either is missing or not positive)"""
    if i0 is None or not series:
        return None
    first, last = series[i0], series[-1]
    if not first or last is None or first <= 0:
        return None
    return last / first - 1.0


def _contributions(dep: dict[str, Any]) -> list[dict[str, Any]]:
    """per-position gain and its share of the total cost in percentage points, best first"""
    cost = dep.get("cost") or 0
    return sorted(({"name": p["name"], "wkn": p["wkn"], "gain": p["gain"], "gain_pct": p["gain_pct"],
                    "share_pp": (p["gain"] / cost * 100.0) if cost > 0 and p["gain"] is not None else None}
                   for p in dep.get("positions", [])), key=lambda x: -(x["gain"] or 0))


def _benchmark_return(bench: list[float | None] | None, sec: list[Any], i0: int | None) -> float | None:
    """total return of the benchmark over the same months as the securities series, or None when it cannot be compared"""
    if bench and i0 is not None and len(bench) == len(sec):
        b_first, b_last = bench[i0], bench[-1]
        if b_first and b_last:
            return b_last / b_first - 1.0
    return None


def _performance(d: Mapping[str, Any], bench: list[float | None] | None, cfg: dict[str, Any], today: str) -> dict[str, Any]:
    """Securities price return and XIRR against the benchmark, crypto gain and the per-position contributions."""
    dep, cb = d.get("depot") or {}, d.get("crypto") or {}
    sec = (d.get("nw") or {}).get("Securities") or []
    i0 = _first(sec)
    months = (len(sec) - i0 - 1) if i0 is not None else 0
    price_ret = _total_return(sec, i0)
    b_ret = _benchmark_return(bench, sec, i0)
    flows, skipped = _securities_flows(d, today)
    return {
        "securities": {"price_return": price_ret, "xirr": xirr(flows) if flows else None, "xirr_skipped_positions": skipped,
                       "xirr_since": dep.get("trades_from"), "bench_return": b_ret,
                       "excess_pp": (price_ret - b_ret) * 100.0 if price_ret is not None and b_ret is not None else None,
                       "bench_name": (cfg.get("index_benchmark") or {}).get("name"), "months": months},
        "crypto": {"gain_pct": cb.get("gain_pct"), "gain": cb.get("gain"), "cost": cb.get("cost"), "status": cb.get("trades_status")},
        "contributions": _contributions(dep),
        "crypto_contributions": [{"name": h["currency"], "gain": h.get("gain"), "gain_pct": h.get("gain_pct")} for h in cb.get("holdings", []) if h.get("gain") is not None],
        "basis": "estimate", "len": months}


def _risk(d: Mapping[str, Any], bench: list[float | None] | None, values: dict[str, Any], cfg: dict[str, Any], months: int) -> dict[str, Any]:
    """Risk of today's holdings over their price history (back-cast): per-class blocks, correlations and the stress test."""
    nw = d.get("nw") or {}
    rf = cfg.get("risk_free", 0.02)
    sec, cry = nw.get("Securities") or [], nw.get("Crypto") or []
    positions = [p for p in (d.get("depot") or {}).get("positions", []) if p["value"]]
    comb = [a + b if a is not None and b is not None else None for a, b in zip(sec, cry)]
    top = sorted(positions, key=lambda p: -p["value"])[:8]
    series = {p["name"]: monthly_returns(p["hist"]) for p in top if p.get("hist")}
    if cry:
        series["Crypto"] = monthly_returns(cry)
    if bench:
        series["Benchmark"] = monthly_returns(bench)
    return {"securities": _risk_block(sec, rf), "crypto": _risk_block(cry, rf), "combined": _risk_block(comb, rf),
            "benchmark": _risk_block(bench, rf) if bench else None, "corr": correlation_matrix(series),
            "stress": stress(values, cfg.get("stress") or {}), "rf": rf, "basis": "model", "len": months}


def _exposure_and_costs(d: Mapping[str, Any], profiles: dict[str, dict[str, Any]] | None, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Concentration / look-through exposure of the depot and its running costs (TER, yield)."""
    dep = d.get("depot") or {}
    positions = [p for p in dep.get("positions", []) if p["value"]]
    cost = dep.get("cost") or 0
    tot = sum(p["value"] for p in positions)
    weights = [p["value"] / tot for p in positions] if tot else []
    agg = aggregate_exposure(positions, profiles)
    exposure = {"top": [{"name": p["name"], "weight": p["value"] / tot} for p in sorted(positions, key=lambda p: -p["value"])[:5]] if tot else [],
                "effective_n": effective_n(weights), "hhi": sum(w * w for w in weights) * HHI_SCALE,
                "by_class": dep.get("classes"), "by_theme": dep.get("themes"),
                "by_country": agg["by_country"], "by_sector": agg["by_sector"], "by_currency": agg["by_currency"],
                "lookthrough": agg["lookthrough"], "coverage": agg["coverage"], "basis": "live" if profiles else "model", "len": None}
    inc = (d.get("income_est") or {}).get("yearly")
    costs = {"ter_pct": agg["ter_pct"], "ter_eur": agg["ter_eur"], "coverage": agg["coverage"]["ter"],
             "yield": (inc / values["Securities"] * 100.0) if inc is not None and values["Securities"] else None,
             "yield_on_cost": (inc / cost * 100.0) if inc is not None and cost > 0 else None, "basis": "estimate", "len": None}
    return exposure, costs


def _allocation(values: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    return {"drift": drift(values, cfg.get("targets") or {}), "values": values, "basis": "live", "len": None}


def _liquidity(d: Mapping[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """How fast each asset class can be turned into cash, and how well cash covers the unfunded Example Fund commitment."""
    wf = d.get("examplefund") or {}
    p_wf, f_wf = wf.get("personal") or {}, wf.get("fund") or {}
    cash = values["Cash"]
    unf = p_wf.get("unfunded")
    return {"ladder": [
        {"label": "Within a week", "eur": cash + values["Securities"] + values["Crypto"], "parts": ["Cash", "Securities", "Crypto"]},
        {"label": "6-12 months (sale of the apartment)", "eur": values["Real estate"], "parts": ["Real estate"]},
        {"label": "Fund term (until %s)" % (f_wf.get("term_end") or "n/a"), "eur": p_wf.get("nav") or 0, "parts": ["Example Fund"]},
        {"label": "No market (wiwin)", "eur": (d.get("wiwin") or {}).get("invested") or 0, "parts": ["wiwin"]}],
        "unfunded_wf": unf, "cash_cover": (cash / unf) if unf else None, "basis": "model", "len": None}


def _private_equity(d: Mapping[str, Any]) -> dict[str, Any]:
    wf = d.get("examplefund") or {}
    p_wf, f_wf = wf.get("personal") or {}, wf.get("fund") or {}
    prev = f_wf.get("prev") or {}
    return {"tvpi": f_wf.get("tvpi"), "dpi": f_wf.get("dpi"), "rvpi": f_wf.get("rvpi"), "irr": f_wf.get("net_irr"),
            "personal": p_wf, "basis": "live" if wf else "n/a", "len": 2 if prev else 1,
            "points": ([{"label": prev.get("label"), "fund_paid_in": prev.get("paid_in"), "fund_nav": prev.get("nav"), "tvpi": prev.get("tvpi")}] if prev else [])
            + ([{"label": "Q%s %s" % (wf.get("report_q"), wf.get("report_year")), "fund_paid_in": f_wf.get("paid_in"), "fund_nav": f_wf.get("nav"), "tvpi": f_wf.get("tvpi")}] if f_wf else [])}


def _real_change(d: Mapping[str, Any], cpi: list[float] | None) -> dict[str, Any]:
    """Real (inflation-adjusted) change of the gross assets over the last 12 months."""
    g = (d.get("nwx") or {}).get("gross") or []
    if cpi and g and len(cpi) == len(g) and len(g) >= 13 and g[-13] and cpi[-13]:
        nominal = g[-1] / g[-13] - 1.0                      # last 12 months (deposits included)
        return {"nominal_change": nominal, "real_change": (1.0 + nominal) / (cpi[-1] / cpi[-13]) - 1.0,
                "gross_real": deflate(g, cpi), "cpi": cpi, "basis": "estimate", "len": 12}
    return {"nominal_change": None, "real_change": None, "gross_real": None, "cpi": None, "basis": "n/a", "len": None}


def build_analytics(d: Mapping[str, Any], bench: list[float | None] | None = None, cpi: list[float] | None = None, profiles: dict[str, dict[str, Any]] | None = None, cfg: dict[str, Any] | None = None) -> AnalyticsResult:
    """Everything the UI needs for the wealth-manager views, from data.json content (see docs/superpowers/specs).
    Composes one small builder per section (performance, risk, exposure, costs, allocation, liquidity, private equity, tax, real)."""
    if cfg is None:
        cfg = DEFAULTS
    axis, nw = d.get("axis") or [], d.get("nw") or {}
    today = (d.get("generated") or dt.date.today().isoformat())[:10]
    values = class_values(d)
    performance = _performance(d, bench, cfg, today)
    exposure, costs = _exposure_and_costs(d, profiles, values)
    first_investment: dict[str, str] = {}
    for k in CLASSES:
        i0 = _first(nw[k]) if nw.get(k) else None
        if i0 is not None:
            first_investment[k] = axis[i0]
    return AnalyticsResult(asof=today, first_investment=first_investment,
                           performance=performance, risk=_risk(d, bench, values, cfg, performance["len"]), exposure=exposure,
                           allocation=_allocation(values, cfg), liquidity=_liquidity(d, values),
                           private_equity=_private_equity(d), costs=costs, tax=_tax(d, today, cfg), real=_real_change(d, cpi))

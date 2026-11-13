"""Typed-in assets over time (v1.20): a house or apartment valued with the national house price index (Eurostat prc_hpi_q), a loan as an annuity,
a fund by what was paid in, any other investment by its value - and the block of numbers the dashboard shows for them.

The pure functions (parse_hpi, property_series, loan_model, fund_model) take plain values; build_assets_block reads the typed assets from the database.
The only web call is fetch_hpi: it sends the two-letter country code and nothing else, and any failure just means "no index, flat line"."""
from __future__ import annotations
import datetime as dt
import re
import sqlite3
from typing import Any, Callable

from ...common import safenet
from ..ingest import db_accounts, db_assets

HPI_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hpi_q?format=JSON&lang=EN&purchase=TOTAL&unit=I15_Q&geo={geo}"
# the countries prc_hpi_q covers, as ISO code -> Eurostat code (Greece is EL there)
_GEO = {c: c for c in "AT BE BG CY CZ DE DK EE ES FI FR HR HU IE IS IT LT LU LV MT NL NO PL PT RO SE SI SK TR".split()}
_GEO["GR"] = "EL"
MAX_LOAN_MONTHS = 1200
_PERIOD = re.compile(r"^\d{4}-Q[1-4]$")


def eurostat_geo(country: str) -> str | None:
    """Eurostat's code for a two-letter country code, or None when the index does not cover it."""
    return _GEO.get((country or "").strip().upper())


def parse_hpi(js: Any) -> dict[str, float]:
    """{'2021-Q1': 104.0, ...} out of a JSON-stat answer (time index as dict or list, values as dict or list); empty for anything else."""
    try:
        cats = js["dimension"]["time"]["category"]["index"]
        values = js["value"]
    except (KeyError, TypeError):
        return {}
    pos = {k: int(v) for k, v in cats.items()} if isinstance(cats, dict) else {k: i for i, k in enumerate(cats)} if isinstance(cats, list) else {}
    out: dict[str, float] = {}
    for period, i in pos.items():
        if not _PERIOD.match(str(period)):
            continue
        v = values.get(str(i)) if isinstance(values, dict) else values[i] if isinstance(values, list) and 0 <= i < len(values) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out[period] = float(v)
    return out


def fetch_hpi(country: str, fetch: Callable[[str], Any] | None = None) -> dict[str, float] | None:
    """The quarterly house price index of a country (None when it is not covered, the service is down or the answer is empty)."""
    geo = eurostat_geo(country)
    if geo is None:
        return None
    get = fetch or safenet.fetch_json
    try:
        idx = parse_hpi(get(HPI_URL.format(geo=geo)))
    except safenet.NET_ERRORS as e:
        safenet.swallowed("house price index", e)
        return None
    return idx or None


def _month(d: dt.date) -> str:
    return f"{d.year}-{d.month:02d}"


def _quarter(m: str) -> str:
    return f"{m[:4]}-Q{(int(m[5:7]) - 1) // 3 + 1}"


def _months(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while f"{y}-{m:02d}" <= last:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _index_at(idx: dict[str, float], q: str) -> float:
    """The index value of a quarter: the quarter itself, else the nearest earlier one, else the first one we know."""
    keys = sorted(idx)
    if q in idx:
        return idx[q]
    earlier = [k for k in keys if k < q]
    return idx[earlier[-1]] if earlier else idx[keys[0]]


def property_series(price: float, purchase_date: str, idx: dict[str, float], today: dt.date, estimate: float | None = None) -> list[tuple[str, float]]:
    """[(month, value)] from the purchase month to today: the purchase price moved with the house price index (the last known quarter carries forward).
    Without an index the line is flat. A typed current estimate pulls the end of the line to that value, in an even slope from the purchase price."""
    first, last = purchase_date[:7], _month(today)
    months = _months(first, last) if first <= last else [first]
    if idx:
        base = _index_at(idx, _quarter(first))
        vals = [price * _index_at(idx, _quarter(m)) / base for m in months]
    else:
        vals = [price] * len(months)
    if estimate is not None and len(months) > 1:
        end = vals[-1] or 1.0
        vals = [v * (1 + (estimate / end - 1) * i / (len(months) - 1)) for i, v in enumerate(vals)]
    elif estimate is not None:
        vals = [estimate]
    pts = [(m, round(v, 2)) for m, v in zip(months, vals)]
    if pts:
        pts[0] = (pts[0][0], round(price, 2))
    return pts


def _month_diff(a: dt.date, b: dt.date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def loan_model(amount: float, start_date: str, rate_pct: float, monthly: float | None = None, end_date: str | None = None,
               today: dt.date | None = None) -> dict[str, Any]:
    """An annuity loan: payments on the day of the month of the start, the first one month after it. Give the monthly payment or the end date
    (then the payment is worked out). Returns {balance, monthly, payoff, series}: balance today, the payment, the month it is paid off (None if the
    payment does not cover the interest) and [(month, balance)] from the start month to today (or payoff)."""
    today = today or dt.date.today()
    start = dt.date.fromisoformat(start_date)
    r = rate_pct / 1200.0
    if monthly is None:
        if not end_date:
            raise ValueError("give the monthly payment or the end date")
        n = max(1, _month_diff(start, dt.date.fromisoformat(end_date)))
        monthly = amount / n if r == 0 else amount * r / (1 - (1 + r) ** -n)
    paid = max(0, _month_diff(start, today) - (1 if today.day < start.day else 0))
    bal, payoff = float(amount), None
    series = [(_month(start), round(bal, 2))]
    y, m = start.year, start.month
    for k in range(1, MAX_LOAN_MONTHS + 1):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        bal = bal * (1 + r) - monthly
        if bal <= 0.005:
            bal, payoff = 0.0, f"{y}-{m:02d}"
        if k <= paid or payoff:
            series.append((f"{y}-{m:02d}", round(bal, 2)))
        if payoff or k >= paid and payoff is None and k >= MAX_LOAN_MONTHS:
            break
        if k == paid:
            now_bal = bal
            # keep looking ahead only to find the payoff month
            sim, yy, mm = bal, y, m
            for _ in range(MAX_LOAN_MONTHS):
                yy, mm = (yy + 1, 1) if mm == 12 else (yy, mm + 1)
                sim = sim * (1 + r) - monthly
                if sim <= 0.005:
                    payoff = f"{yy}-{mm:02d}"
                    break
            if paid == 0:
                now_bal = amount
            return {"balance": round(now_bal, 2), "monthly": round(monthly, 2), "payoff": payoff, "series": series}
    balance = 0.0 if payoff and payoff <= _month(today) else float(series[-1][1])
    if paid == 0:
        balance = float(amount)
    return {"balance": round(balance, 2), "monthly": round(monthly, 2), "payoff": payoff, "series": series}


def fund_model(payments: list[dict[str, Any]], current_value: float | None, today: dt.date) -> dict[str, Any]:
    """What was paid in so far (payments dated after today wait), the value (typed, else at cost) and the gain when a value is typed."""
    invested = round(sum(float(p["amount"]) for p in payments if p["date"] <= today.isoformat()), 2)
    if current_value is None:
        return {"invested": invested, "value": invested, "gain": None, "gain_pct": None, "basis": "at cost"}
    gain = round(current_value - invested, 2)
    pct = round(gain / invested * 100, 1) if invested else None
    return {"invested": invested, "value": round(float(current_value), 2), "gain": gain, "gain_pct": pct, "basis": "typed"}


def fund_series(payments: list[dict[str, Any]], value: float, today: dt.date) -> list[tuple[str, float]]:
    """[(month, value)] from the first payment to this month: what was paid in so far, the last month at the current value."""
    paid = sorted((p["date"], float(p["amount"])) for p in payments if p["date"] <= today.isoformat())
    if not paid:
        return []
    out = [(m, round(sum(a for d, a in paid if d[:7] <= m), 2)) for m in _months(paid[0][0][:7], _month(today))]
    out[-1] = (out[-1][0], round(float(value), 2))
    return out


def to_axis(series: list[tuple[str, float]], axis: list[str]) -> list[float | None]:
    """The value for each month of the shared axis: None before the first point, the last known value carried on after the last."""
    by = dict(series)
    out: list[float | None] = []
    last: float | None = None
    for m in axis:
        if m in by:
            last = by[m]
        elif last is None and series and m > series[0][0]:      # the series starts before the axis does
            last = [v for k, v in series if k < m][-1] if any(k < m for k, _ in series) else None
        out.append(last)
    return out


def _add(target: list[Any], vals: list[float | None]) -> None:
    for i, v in enumerate(vals):
        if v is not None:
            target[i] = (target[i] or 0) + v


def add_to_nw(nw: dict[str, list[Any]], loan_series: list[float], block: dict[str, Any] | None, axis: list[str]) -> list[float]:
    """Puts the typed assets into the net-worth series: property -> Real estate, funds -> Securities, other -> Private equity (the classes the
    dashboard already has). Returns the loan balance per month including the typed loans. nw is changed in place."""
    if not block:
        return list(loan_series)
    for p in block["property"]:
        _add(nw["Real estate"], to_axis(p["series"], axis))
    for f in block["funds"]:
        _add(nw["Securities"], to_axis(f["series"], axis))
    for o in block["other"]:
        since = (o.get("date") or "")[:7]
        _add(nw["Private equity"], [float(o["value"]) if not since or m >= since else None for m in axis])
    loans = list(loan_series)
    for lo in block["loans"]:
        for i, v in enumerate(to_axis(lo["series"], axis)):
            loans[i] = loans[i] + (v or 0)
    return loans


def build_assets_block(conn: sqlite3.Connection, today: dt.date, fetch: Callable[[str], dict[str, float] | None] | None = None) -> dict[str, Any] | None:
    """The numbers for the typed assets: {property, loans, funds, other, totals}, or None when nothing was typed in.
    fetch(country) gives the house price index of a country (default: Eurostat); it is asked once per country."""
    items = db_assets.list_assets(conn)
    balances = account_balances(conn)
    if not items and not balances:
        return None
    get = fetch or fetch_hpi
    cache: dict[str, dict[str, float] | None] = {}
    props: list[dict[str, Any]] = []
    loans: list[dict[str, Any]] = []
    funds: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for it in items:
        f, aid, name = it["fields"], it["account_id"], it["name"]
        if it["kind"] == "property":
            c = f["country"]
            if c not in cache:
                cache[c] = get(c)
            idx = cache[c] or {}
            est = f.get("current_estimate")
            series = property_series(f["purchase_price"], f["purchase_date"], idx, today, est)
            basis = "your estimate" if est is not None else "estimate" if idx else "purchase price"
            props.append({"account_id": aid, "name": name, "country": c, "purchase_price": f["purchase_price"], "purchase_date": f["purchase_date"],
                          "value": float(est) if est is not None else series[-1][1], "basis": basis, "series": series})
        elif it["kind"] == "loan":
            m = loan_model(f["amount"], f["start_date"], f["rate_pct"], f.get("monthly"), f.get("end_date"), today)
            loans.append({"account_id": aid, "name": name, "amount": f["amount"], "rate_pct": f["rate_pct"], "property": f.get("property"),
                          "balance": m["balance"], "monthly": m["monthly"], "payoff": m["payoff"], "series": m["series"]})
        elif it["kind"] == "fund":
            m = fund_model(f["payments"], f.get("current_value"), today)
            funds.append({"account_id": aid, "name": name, "isin": f.get("isin"), **m, "series": fund_series(f["payments"], m["value"], today)})
        else:
            other.append({"account_id": aid, "name": name, "value": float(f["value"]), "date": f.get("date")})
    for p in props:
        owed = sum(lo["balance"] for lo in loans if lo["property"] and lo["property"] == p["name"])
        p["equity"] = round(p["value"] - owed, 2)
    totals = {"property": round(sum(p["value"] for p in props), 2), "liabilities": round(sum(lo["balance"] for lo in loans), 2),
              "funds": round(sum(x["value"] for x in funds), 2), "other": round(sum(o["value"] for o in other), 2),
              "cash": round(sum(b["balance"] for b in balances), 2)}
    return {"property": props, "loans": loans, "funds": funds, "other": other, "balances": balances, "totals": totals}


def account_balances(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """The typed balances of bank accounts whose files carry none: [{id, name, balance, date, basis}]."""
    names = {a["id"]: a["name"] for a in db_accounts.list_accounts(conn)}
    return [{"id": aid, "name": names.get(aid, ""), "balance": bal, "date": d, "basis": "typed"} for aid, (bal, d) in db_assets.typed_balances(conn).items() if aid in names]

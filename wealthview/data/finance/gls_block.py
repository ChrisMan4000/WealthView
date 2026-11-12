"""
WealthView - GLS booking analysis (pure functions on the booking rows: accounts, monthly flows, category totals, recurring costs,
month-end balances, cash history). build_gls_block assembles the "gls" block of data.json. No files, no network.
"""
from __future__ import annotations
from typing import Any
import datetime as dt
from collections import defaultdict
from .categories import classify
from ...common.parsing import iso, round2
from ...common.config import oneoff_threshold
from ...common.timeutil import today
from ..ingest.gls_parse import booking_label
from .ownaccounts import OwnAccounts, cash_flow_events
from ...common.timeutil import month_key, month_list
from ...common.types.bookings import ACCOUNT_KINDS, CASH_KINDS, BalanceHistory, BookingRow, CategoryTotal, GlsAccount, GlsBlock, GlsCategories, GlsFlow, Kind, RecentBooking, RecurringCost

def _gls_accounts(rows: list[BookingRow]) -> list[GlsAccount]:
    accounts: list[GlsAccount] = []
    seen: set[str] = set()
    for r in rows:
        if r["iban"] in seen:
            continue
        seen.add(r["iban"])
        accounts.append(GlsAccount(
            iban_tail=r["iban"][-4:], name=r["account"], kind=r["kind"],
            balance=round2(r["balance"]), last_booking=iso(r["date"]),
        ))
    order = {k: i for i, k in enumerate(ACCOUNT_KINDS)}
    accounts.sort(key=lambda a: order.get(a["kind"], 9))
    return accounts


def _flow_series(months: list[str], big: float, inc: dict[str, float], exp: dict[str, float], big_in: dict[str, float],
                 big_out: dict[str, float], inv_out: dict[str, float], inv_in: dict[str, float]) -> GlsFlow:
    """the monthly lists of the flow block, one value per month (missing months count as 0)"""
    income = [round2(inc[m]) for m in months]
    expense = [round2(exp[m]) for m in months]
    return GlsFlow(
        months=months,
        income=income,
        expense=expense,
        oneoff_in=[round2(big_in[m]) for m in months],
        oneoff_out=[round2(big_out[m]) for m in months],
        invest_out=[round2(inv_out[m]) for m in months],
        invest_in=[round2(inv_in[m]) for m in months],
        oneoff_threshold=big,
        net=[round2(i - e) for i, e in zip(income, expense)],
    )


def _monthly_flow(rows: list[BookingRow], own: OwnAccounts) -> dict[str, Any]:
    """monthly income / spending / one-offs / investing of Giro + credit card, plus the rows behind the category tables"""
    months = month_list(24, today())
    big = oneoff_threshold()
    inc: defaultdict[str, float] = defaultdict(float)
    exp: defaultdict[str, float] = defaultdict(float)
    big_in: defaultdict[str, float] = defaultdict(float)
    big_out: defaultdict[str, float] = defaultdict(float)
    inv_out: defaultdict[str, float] = defaultdict(float)
    inv_in: defaultdict[str, float] = defaultdict(float)
    cat_rows: list[Any] = []
    large: list[Any] = []  # cat_rows: (date, cat, amount, merchant)
    for r, mk, kind in cash_flow_events(rows, own):
        if kind == "invest":  # securities buy / sell and World Fund / wiwin transfers = investing, not spending
            (inv_in if r["amount"] > 0 else inv_out)[mk] += abs(r["amount"])
            continue
        if abs(r["amount"]) >= big:  # large one-offs are shown separately, not in run-rate
            (big_in if r["amount"] > 0 else big_out)[mk] += abs(r["amount"])
            if r["date"] >= today() - dt.timedelta(days=365):
                large.append(dict(d=iso(r["date"]), n=booking_label(r), v=round2(r["amount"]), c=r["cat"] or "-"))
            continue
        if kind == "income":
            inc[mk] += r["amount"]
        else:
            exp[mk] += -r["amount"]
            cat_rows.append((r["date"], classify(r), -r["amount"], booking_label(r)))
    flow = _flow_series(months, big, inc, exp, big_in, big_out, inv_out, inv_in)
    full = months[:-1]  # last complete months; the averages and invested12 are added by analysis/totals.apply_flow_kpis from the flow model
    last12 = full[-12:]
    last3 = full[-3:]
    large.sort(key=lambda x: x["d"], reverse=True)
    return dict(flow=flow, cat_rows=cat_rows, large=large, last12=last12, last3=last3)


def _category_totals(cat_rows: list[Any], ms: set[str]) -> list[CategoryTotal]:
    agg: defaultdict[str, float] = defaultdict(float)
    for d, c, v, _ in cat_rows:
        if month_key(d) in ms:
            agg[c] += v
    items = sorted(agg.items(), key=lambda kv: -kv[1])
    return [CategoryTotal(c=k, v=round2(v)) for k, v in items]


def _recurring_costs(rows: list[BookingRow], own: OwnAccounts) -> list[RecurringCost]:
    """Giro payments of the same label and amount in at least 4 of the last ~6 months"""
    rec = defaultdict(set)
    rec_amt: dict[tuple[str, int], float] = {}
    cut6 = today() - dt.timedelta(days=190)
    for r in rows:
        if r["kind"] == "giro" and r["amount"] < 0 and r["date"] >= cut6 and not own.internal(r) and not own.card_settlement(r):
            if r["typ"].lower() in ("abschluss",):
                continue
            label = (r["counterparty"] or r["typ"])[:26]
            if r["typ"].lower().startswith("dauerauftrag"):
                label = r["purpose"].split("IBAN")[0].strip()[:34] or label
            k = (label, round(r["amount"]))
            rec[k].add(month_key(r["date"]))
            rec_amt[k] = r["amount"]
    recurring: list[RecurringCost] = [
        RecurringCost(label=k[0], amount=round2(-rec_amt[k]), months=len(v))
        for k, v in rec.items() if len(v) >= 4
    ]
    recurring.sort(key=lambda x: -x["amount"])
    return recurring[:12]


def month_end_balances(rows: list[BookingRow], months: list[str], kinds: tuple[Kind, ...]) -> BalanceHistory:
    """{'months': months, kind: [balance at each month end, carried forward when a month has no booking]}"""
    out = BalanceHistory(months=months)
    for kind in kinds:
        by_m: dict[str, Any] = {}
        for r in sorted([x for x in rows if x["kind"] == kind], key=lambda x: x["date"]):
            if r["balance"] is not None:       # a booking without a balance keeps the carried-forward one
                by_m[month_key(r["date"])] = r["balance"]
        series: list[Any] = []
        last = None
        for m in months:
            if m in by_m:
                last = by_m[m]
            series.append(round2(last))
        out[kind] = series
    return out


def _cash_history(rows: list[BookingRow]) -> BalanceHistory:
    """month-end balance per account kind over the last 36 months"""
    return month_end_balances(rows, month_list(36, today()), CASH_KINDS)


def _recent_bookings(rows: list[BookingRow], own: OwnAccounts) -> tuple[list[RecentBooking], list[RecentBooking]]:
    """-> (the 16 newest, all) non-internal Giro / card bookings"""
    recent: list[RecentBooking] = []
    all_bookings: list[RecentBooking] = []
    for r in rows:
        if own.is_external(r):
            cat = classify(r)
            all_bookings.append(RecentBooking(d=iso(r["date"]), n=booking_label(r), v=round2(r["amount"]), c=cat))
            if len(recent) < 16:
                recent.append(RecentBooking(d=iso(r["date"]), n=booking_label(r), v=round2(r["amount"]), c=cat, src=r["kind"]))
    return recent, all_bookings


def build_gls_block(rows: list[BookingRow]) -> GlsBlock | None:
    """The per-account GLS dashboard block (accounts, 24-month flow, category tables, recurring costs, recent bookings).
    The 12-month KPIs, income sources and top merchants are NOT computed here: analysis/totals.apply_flow_kpis takes them
    from bookings.build_flow_model, the single owner of those numbers."""
    if not rows:
        return None
    own = OwnAccounts(rows)
    fl = _monthly_flow(rows, own)
    categories = GlsCategories(m3=_category_totals(fl["cat_rows"], set(fl["last3"])), m12=_category_totals(fl["cat_rows"], set(fl["last12"])))
    recent, all_bookings = _recent_bookings(rows, own)
    return GlsBlock(accounts=_gls_accounts(rows), flow=fl["flow"], categories=categories,
                recurring=_recurring_costs(rows, own), cash_history=_cash_history(rows),
                recent=recent, all_bookings=all_bookings, large=fl["large"][:12], last_booking=iso(rows[0]["date"]))

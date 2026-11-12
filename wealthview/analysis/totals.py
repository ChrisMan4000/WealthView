"""Totals and KPIs of the dashboard: asset groups, liabilities, net worth, last-12-month flows, runway and the merchant logo keys."""
from __future__ import annotations
from typing import Any
from collections.abc import Mapping
from ..common import config
from ..common.parsing import round2
from ..common.types.bookings import FlowModel, GlsAccount, GlsBlock, Kind, PaypalInfo, RecentBooking
from ..common.types.datajson import DataJson, NwSeries, Totals
from ..common.types.depot import AssetGroup
from ..data.finance.bookings import merchant_display
from ..common.profile import load_profile
from ..data.finance.models import tax_model, apartment_sale_model, no_tax_estimate


def compute_totals(data: DataJson) -> None:
    """Fills data["totals"] (asset groups, liabilities, net, tax) and data["tax"] from the already loaded sources."""
    t = data["totals"]
    ap, depot, cb, wf, wiwin = data.get("apartment"), data.get("depot"), data.get("crypto"), data.get("worldfund"), data.get("wiwin")    # absent = module off
    cash_total = t["giro"] + t["tages"] + t["card"] + t["shares"] + (t["paypal"] or 0)
    groups = [
        AssetGroup(k="Real estate", v=round2(ap["value_used"]) if ap else 0),
        AssetGroup(k="Securities", v=round2(depot["total"]) if depot else 0),
        AssetGroup(k="Private equity", v=round2((wf["personal"]["nav"] if wf else 0) + (wiwin["invested"] if wiwin else 0))),
        AssetGroup(k="Cash", v=round2(cash_total)),
        AssetGroup(k="Crypto", v=round2(cb["total_eur"]) if cb else 0),
    ]
    assets = sum(x["v"] for x in groups)
    loan = data.get("loan")
    liab = (loan["balance"] if loan else 0) + sum(v for v in config.setting("liabilities", {}).values() if isinstance(v, (int, float)))
    german = load_profile().tax_country == "DE"      # only German rules are modelled: any other country shows "no tax estimate"
    t["assets"] = round2(assets)
    t["groups"] = groups
    t["liabilities"] = round2(liab)
    t["net"] = round2(assets - liab)
    if german:
        tax = tax_model(depot, wf)
        tax_eur = tax["tax"]
        data["tax"] = tax
    else:
        tax_eur = 0.0
        data["tax"] = no_tax_estimate()     # type: ignore[typeddict-item]
    t["tax"] = tax_eur
    t["net_after_tax"] = round2(assets - liab - tax_eur)
    if not ap:
        data.pop("apartment_sale", None)
    else:
        data["apartment_sale"] = apartment_sale_model(ap, loan) if german else no_tax_estimate()


def group_bookings(items: list[RecentBooking], cap: int = 500) -> dict[str, list[list[Any]]]:
    """{display name: [[date, amount, category], ...]} newest first, at most `cap` per company (for the booking-history pop-up)."""
    out: dict[str, list[list[Any]]] = {}
    for it in sorted(items, key=lambda x: x["d"] or "", reverse=True):
        lst = out.setdefault(merchant_display(it["n"])[0], [])
        if len(lst) < cap:
            lst.append([it["d"], it["v"], it.get("c")])
    return out


def _balance(accounts: Mapping[Kind, GlsAccount], kind: Kind) -> float:
    """Balance of the account of this kind (0 when there is none or it has no balance)."""
    acct = accounts.get(kind)
    return (acct["balance"] if acct else None) or 0


def account_totals(gls: GlsBlock | None, paypal: PaypalInfo) -> tuple[Totals, float, float]:
    """Account balances for data["totals"]; also returns the giro and tages balances."""
    accounts = {a["kind"]: a for a in (gls["accounts"] if gls else [])}
    giro, tages = _balance(accounts, "giro"), _balance(accounts, "tages")
    card, shares = _balance(accounts, "card"), _balance(accounts, "shares")
    totals = Totals(giro=round2(giro), tages=round2(tages), card=round2(card), shares=round2(shares), paypal=paypal["balance"])
    return totals, giro, tages


def _avg(values: list[float]) -> float:
    """Rounded average of a list (0 for an empty one)."""
    return round2(sum(values) / max(1, len(values)))


def apply_flow_kpis(g: GlsBlock | None, flows: FlowModel | None) -> None:
    """Last-12-month KPIs of the GLS block (income, spending, invested), from bookings.build_flow_model: one-offs are included."""
    if not g:
        return
    all_bookings = g.pop("all_bookings", None)       # only needed for the grouped history below
    if flows:
        income, expense, invested = flows["income"][:-1], flows["expense"][:-1], flows["invested"][:-1]   # the last month is incomplete
        g["flow"]["avg12_income"] = _avg(income[-12:])
        g["flow"]["avg12_expense"] = _avg(expense[-12:])
        g["flow"]["avg3_expense"] = _avg(expense[-3:])
        g["flow"]["invested12"] = round2(sum(invested[-12:]))
        g["income_sources"] = flows["income_sources"]
        g["merchants"] = flows["top_spenders"]["y1"][:12]
        g["bookings"] = group_bookings(all_bookings or [])
        for it in g["recent"]:
            shown, dm = merchant_display(it["n"])
            if dm:
                it["lg"] = "m:" + shown
                it["n"] = shown


def apply_runway(g: GlsBlock | None, giro: float, tages: float) -> None:
    """Months the giro + savings balance lasts at the average spending of the last 3 months (None without spending)."""
    if g:
        g["runway_months"] = round2((giro + tages) / g["flow"]["avg3_expense"]) if g["flow"]["avg3_expense"] else None


def logo_extras(flows: FlowModel | None, g: GlsBlock | None) -> dict[str, str]:
    """Merchant logo keys -> domains for the spenders and the recent bookings."""
    extra: dict[str, str] = {}
    if flows:
        for lst in list(flows["top_spenders"].values()):
            for m in lst:
                if m["dom"]:
                    extra["m:" + m["n"]] = m["dom"]
    for it in (g["recent"] if g else []):
        if it.get("lg"):
            dm = merchant_display(it["n"])[1]
            if dm:
                extra[it["lg"]] = dm
    return extra


def logo_candidates(flows: FlowModel | None, g: GlsBlock | None) -> list[tuple[str, str, str]]:
    """(logo key, merchant name, category) for the spenders that have NO known domain yet: the names logo_fetch may look up online."""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for lst in (flows["top_spenders"].values() if flows else []):
        for m in lst:
            if not m["dom"] and m["n"] not in seen:
                seen.add(m["n"])
                out.append(("m:" + m["n"], m["n"], m.get("cat") or ""))
    return out


def gross_and_net(nw: NwSeries, loan_s: list[float], n: int) -> tuple[list[float], list[float]]:
    """Rounded gross wealth per month and the net series (gross minus the loan balance)."""
    gross = [sum((nw[k][i] or 0) for k in nw) for i in range(n)]
    return [round(v, 0) for v in gross], [round(gv - lv, 0) for gv, lv in zip(gross, loan_s)]

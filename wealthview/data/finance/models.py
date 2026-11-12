"""Valuation models for WealthView: apartment value, family loan, German tax estimate and the long-term net-worth series.

Pure functions on the data dicts that refresh.py assembles (no network, no files).
"""
from __future__ import annotations
from typing import Any, cast
from collections.abc import Mapping, Sequence
from ...common.config import DEFAULTS, section, setting
from ...common.parsing import round2
from ...common.timeutil import axis, mrange, now_month
from ...common.types.bookings import ACCOUNT_KINDS, BalanceHistory, PaypalInfo
from ...common.types.datajson import Apartment, Loan, NwSeries, TaxEstimate, WorldFund
from ...common.types.depot import CryptoBlock, Depot


NO_TAX_NOTE = "no tax estimate"


def no_tax_estimate() -> dict[str, str]:
    """What replaces a tax block when the profile's tax country has no rules here (only Germany is modelled)."""
    return {"note": NO_TAX_NOTE}


# -------------------------------------------------------------- apartment
def interp_price(bench: dict[str, Any], ym: str) -> float:
    """EUR/sqm at month ym; yearly values sit at mid-year (July), linear in between."""
    pts = sorted((int(y) + 6.0 / 12, float(v)) for y, v in bench.items())
    x = int(ym[:4]) + (int(ym[5:7]) - 0.5) / 12
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]         # not reachable: x lies between the first and last point, so one pair above matches


def apartment_model() -> Apartment:
    """The apartment block: the config.json settings plus the benchmark value series, estimate and gain."""
    ap = dict(section("apartment"))
    pm = ap["purchase_date"][:7]
    base = interp_price(ap["benchmark"], pm)
    series: list[float | None] = []
    for m in axis():
        if m < pm:
            series.append(None)
        else:
            series.append(round(ap["purchase_price"] * interp_price(ap["benchmark"], m) / base, 0))
    now_est = series[-1]
    if now_est is None:
        raise ValueError("apartment.purchase_date is in the future")
    out = cast(Apartment, dict(ap))     # config.json is user-edited JSON: the keys are checked here, not by the type
    if ap.get("benchmark2"):
        b2 = ap["benchmark2"]
        base2 = interp_price(b2, pm)
        out["series2"] = [None if m < pm else round(ap["purchase_price"] * interp_price(b2, m) / base2, 0) for m in axis()]
    out["series"] = series
    out["estimate"] = now_est
    out["purchase_per_sqm"] = round2(ap["purchase_price"] / ap["sqm"])
    out["estimate_per_sqm"] = round2(now_est / ap["sqm"])
    out["gain"] = round2(now_est - ap["purchase_price"])
    out["gain_pct"] = round2((now_est / ap["purchase_price"] - 1) * 100)
    out["value_used"] = ap.get("current_value") or (now_est if ap.get("use_estimate", True) else ap["purchase_price"])
    return out


# ------------------------------------------------------------ loan (mum)
def loan_model() -> Loan | None:
    L = setting("loan")
    if not L:
        return None
    start, pr, mo = L["start"][:7], float(L["principal"]), float(L["monthly"])
    series = []
    for m in axis():
        k = len(mrange(start, m)) if m >= start else 0
        series.append(round(max(0.0, pr - mo * k), 0))
    paid_months = len(mrange(start, now_month())) if now_month() >= start else 0
    bal = max(0.0, pr - mo * paid_months)
    left = int(-(-bal // mo)) if mo else None
    y, mon = int(now_month()[:4]), int(now_month()[5:7]) + (left or 0)
    y += (mon - 1) // 12
    mon = (mon - 1) % 12 + 1
    return Loan(lender=L.get("lender", "Family"), principal=pr, monthly=mo, start=start, balance=round2(bal), repaid=round2(pr - bal),
                months_paid=paid_months, months_left=left, payoff=f"{y}-{mon:02d}", series=series)


# ------------------------------------------------------------- German tax
def income_tax_2026(zve: float) -> float:
    """Einkommensteuer-Grundtarif 2026 (section 32a EStG, single): 0 up to the Grundfreibetrag (12,348 EUR), then the progressive zones."""
    x = float(int(max(0.0, zve)))
    if x <= 12348:
        return 0.0
    if x <= 17799:
        y = (x - 12348) / 10000
        return float(int((914.51 * y + 1400) * y))
    if x <= 69878:
        z = (x - 17799) / 10000
        return float(int((173.1 * z + 2397) * z + 1034.87))
    if x <= 277825:
        return float(int(0.42 * x - 11135.63))
    return float(int(0.45 * x - 19470.38))


def soli(tax: float) -> float:
    """Solidarity surcharge for a single filer: nothing up to 20,350 EUR tax, then phased in (max 5.5%, at most 11.9% of the excess)."""
    return 0.0 if tax <= 20350 else round2(min(0.055 * tax, 0.119 * (tax - 20350)))


def _gains_tax(gain: float, T: Mapping[str, Any]) -> dict[str, float | str]:
    """Tax on capital gains `gain` (EUR): flat Abgeltungsteuer vs the personal tariff (Guenstigerpruefung, section 32d (6) EStG)."""
    rate = float(T["rate_pct"]) / 100.0
    allow = float(T["allowance_eur"])
    other = float(T.get("other_income_eur", 0)) - float(T.get("other_deductions_eur", 0))
    taxable = max(0.0, gain - allow)
    flat = taxable * rate
    base = max(0.0, other - float(T.get("sonderausgaben_pauschbetrag_eur", 36)))
    zve = base + taxable
    tariff = income_tax_2026(zve) + 0.0
    tariff += soli(tariff)
    tariff_extra = tariff - (income_tax_2026(base) + soli(income_tax_2026(base)))
    use_tariff = tariff_extra < flat
    return {"taxable": taxable, "flat": flat, "tariff": max(0.0, tariff_extra), "tax": min(flat, max(0.0, tariff_extra)),
            "method": "personal tariff (Guenstigerpruefung)" if use_tariff else "flat 26.375%"}


def tax_model(depot: Depot | None, wf: WorldFund | None) -> TaxEstimate:
    T = {**DEFAULTS["tax"], **(setting("tax", {}) or {})}
    rate = float(T["rate_pct"]) / 100.0
    allow = float(T["allowance_eur"])
    gb = float(T["grundfreibetrag_eur"])
    sec_gain = sum((p["gain"] or 0) for p in (depot["positions"] if depot else []))
    pe_gain = 0.0
    if wf:
        pe_gain = max(0.0, wf["personal"]["nav"] - wf["personal"]["paid_in"])
    g = _gains_tax(sec_gain + pe_gain, T)
    # how much gain stays tax free: allowance + (no other income) Grundfreibetrag after the 36 EUR Sonderausgaben-Pauschbetrag
    headroom = allow + max(0.0, gb - max(0.0, float(T.get("other_income_eur", 0)) - float(T.get("other_deductions_eur", 0)))) \
        + float(T.get("sonderausgaben_pauschbetrag_eur", 36))
    return TaxEstimate(rate_pct=round(rate * 100, 3), allowance=allow, securities_gain=round2(sec_gain), pe_gain=round2(pe_gain),
                taxable=round2(float(g["taxable"])), tax=round2(float(g["tax"])),
                flat_tax=round2(float(g["flat"])), tariff_tax=round2(float(g["tariff"])), method=str(g["method"]),
                grundfreibetrag=gb, tax_free_headroom=round2(headroom),
                crypto_note="Crypto assumed held > 1 year (tax-free in Germany)",
                real_estate_note="Owner-occupied apartment: no tax on a sale (own use in the sale year and the two years before)",
                note=f"Estimate of the tax if everything were sold today: lower of flat {rate * 100:g}% (incl. Soli) and your personal tariff "
                     f"after the full Grundfreibetrag of {gb:,.0f} EUR (single, no other income, no church tax), {allow:,.0f} EUR allowance. Not tax advice.")


def apartment_sale_model(apt: Apartment, loan: Loan | None, depot_tax_other: float = 0.0) -> dict[str, Any]:
    """Taxes and net proceeds if the apartment were sold today (section 23 EStG; Germany; single, no church tax)."""
    T = {**DEFAULTS["tax"], **(setting("tax", {}) or {})}
    S = {**DEFAULTS["apartment_sale"], **(apt.get("sale") or {})}      # type: ignore[call-overload]
    value = float(apt.get("value_used") or apt.get("estimate") or 0)
    buy = float(apt.get("purchase_price") or 0)
    pm = str(apt.get("purchase_date") or now_month())[:7]
    y, m = int(pm[:4]), int(pm[5:7])
    free_from = f"{y + 10}-{m:02d}"
    today = now_month()
    within = today < free_from                      # speculation period: sale within 10 years after the purchase contract
    sell_costs = value * float(S["selling_cost_pct"]) / 100.0
    buy_costs = float(S["acquisition_costs_eur"])
    gain = value - sell_costs - buy - buy_costs
    exempt = bool(S["own_use"])
    taxable_gain = gain if (within and not exempt) else 0.0
    free_limit = taxable_gain < float(S["freigrenze_eur"])     # Freigrenze: below 1,000 EUR nothing, above it everything
    zve = float(T.get("other_income_eur", 0)) + (0.0 if free_limit else max(0.0, taxable_gain))
    tax_all = income_tax_2026(zve)
    tax_all += soli(tax_all)
    scenario_tax = round2(max(0.0, tax_all))
    tax = scenario_tax if (within and not exempt) else 0.0
    bal = float(loan["balance"]) if loan else 0.0
    return {"value": round2(value), "purchase_price": round2(buy), "selling_costs": round2(sell_costs), "acquisition_costs": round2(buy_costs),
            "gain": round2(gain), "speculation_until": free_from, "within_speculation_period": within, "own_use_exempt": exempt,
            "tax": round2(tax), "tax_if_not_exempt": round2(max(0.0, (income_tax_2026(max(0.0, gain)) + soli(income_tax_2026(max(0.0, gain)))) if within and gain >= float(S["freigrenze_eur"]) else 0.0)),
            "loan_balance": round2(bal), "net_proceeds": round2(value - sell_costs - tax - bal),
            "notes": ["Sale tax (section 23 EStG): only if sold within 10 years of the purchase contract and not lived in by you in the sale year and the two years before.",
                      "Own-use exemption set to " + ("ON: no tax." if exempt else "OFF: gain taxed at your personal tariff."),
                      "Buyer pays the Grunderwerbsteuer; you pay your broker share and notary/land-register costs for deleting the mortgage. No church tax.",
                      "Not tax advice."]}


# --------------------------------------------------------------- net worth
def _held_value_series(holdings: Sequence[Mapping[str, Any]], qty_key: str, n: int) -> list[float | None]:
    """sum of quantity x price history over the month axis, rounded to whole euros"""
    tot = [0.0] * n
    for p in holdings:
        if p.get("hist") and p.get(qty_key):
            for i in range(n):
                tot[i] += p[qty_key] * (p["hist"][i] or 0)
    return [round(v, 0) for v in tot]


def _cash_series(g_bal: BalanceHistory | None, pp: PaypalInfo | None, n: int) -> list[float | None]:
    cash: list[float | None] = [None] * n
    if g_bal:
        for i, m in enumerate(axis()):
            if m in g_bal["months"]:
                j = g_bal["months"].index(m)
                tot = sum((g_bal[k][j] or 0) for k in ACCOUNT_KINDS)
                cash[i] = round(tot + ((pp["balance"] if pp else None) or 0), 0)
    return cash


def _worldfund_series(wf: WorldFund | None, n: int) -> list[float | None]:
    """World Fund NAV per month: linear between the two reported quarters, the latest NAV afterwards"""
    pe: list[float | None] = [None] * n
    if not wf:
        return pe
    year, qtr = int(wf.get("report_year", 2026)), int(wf.get("report_q", 2))      # the latest report's quarter end is the second anchor
    prev_year, prev_qtr = (year, qtr - 1) if qtr > 1 else (year - 1, 4)
    prev_key, cur_key = f"{prev_year}-{prev_qtr * 3:02d}", f"{year}-{qtr * 3:02d}"
    prev_nav, nav = wf["personal"].get("nav_prev_quarter"), wf["personal"]["nav"]
    for i, m in enumerate(axis()):
        if m < prev_key:
            continue
        if m <= cur_key:
            k = (int(m[:4]) * 12 + int(m[5:7]) - (prev_year * 12 + prev_qtr * 3)) / 3.0
            pe[i] = prev_nav + (nav - prev_nav) * k if prev_nav else nav
        else:
            pe[i] = nav
    return pe


def _real_estate_series(ap: Apartment) -> list[float | None]:
    """the apartment's value per month: the estimate series, or (use_estimate off) the purchase price from the purchase month on"""
    if ap.get("use_estimate", True):
        return list(ap["series"])
    return [ap["purchase_price"] if m >= ap["purchase_date"][:7] else None for m in axis()]


def _add_wiwin(pe: list[float | None], cash: list[float | None]) -> None:
    """add the money put into wiwin (config) to the private-equity series, from its start month on (in place)"""
    add = section("wiwin")["invested"]
    wsince = (section("wiwin").get("since") or "")[:7] or None
    for i, m in enumerate(axis()):
        w = add if (wsince and m >= wsince) or (not wsince and cash[i] is not None) else 0
        if pe[i] is not None or w:
            pe[i] = round((pe[i] or 0) + w, 0)


def nw_series(depot: Depot | None, cb: CryptoBlock | None, wf: WorldFund | None, ap: Apartment | None,
              g_bal: BalanceHistory | None, pp: PaypalInfo | None, wiwin: bool = True) -> NwSeries:
    """net worth per asset class and month: Real estate, Securities, Crypto, Cash, Private equity.
    ap None (apartment module off) gives an empty Real estate series; wiwin False leaves wiwin out of Private equity."""
    n = len(axis())
    nw: NwSeries = {}
    nw["Real estate"] = _real_estate_series(ap) if ap else [None] * n
    nw["Securities"] = _held_value_series(depot["positions"] if depot else [], "qty", n)
    nw["Crypto"] = _held_value_series(cb.get("holdings", []) if cb else [], "amount", n)
    cash = nw["Cash"] = _cash_series(g_bal, pp, n)
    pe = _worldfund_series(wf, n)
    if wiwin:
        _add_wiwin(pe, cash)
    nw["Private equity"] = pe
    return nw

"""Booking classification and cash-flow analysis for the GLS rows (pure functions on the booking dicts).

classify() (imported from categories.py) sorts a booking into an expense category, merchant_and_domain() finds the merchant, build_flow_model() builds the monthly
income / expense / category numbers and balance history, spending_rows() lists the real spending. No network, no files.
"""
from __future__ import annotations
from functools import lru_cache
from typing import Any
import re
import datetime as dt
from collections import defaultdict

from ...common.types.bookings import ACCOUNT_KINDS, BalanceHistory, BookingRow, FlowModel, MonthlySeries, NameValue, Spender, SpendingRow
from .ownaccounts import OwnAccounts, cash_flow_events
from . import categories
from .categories import SONSTIGES, classify
from . import gls_block
from ..ingest import gls_parse
from ...common.config import oneoff_threshold, setting
from ...common.timeutil import today, now_month
from ...common.parsing import round2
from ...common.timeutil import month_key, mrange

# merchant -> (pattern, display name, web domain for the logo)
MERCHANTS = [
    (r"amazon|amzn", "Amazon", "amazon.de"), (r"\brewe\b", "REWE", "rewe.de"),
    (r"\bedeka\b", "EDEKA", "edeka.de"), (r"\blidl\b", "Lidl", "lidl.de"), (r"\baldi\b", "ALDI", "aldi.de"),
    (r"\bnetto\b", "Netto", "netto-online.de"), (r"\bpenny\b", "Penny", "penny.de"), (r"rossmann", "Rossmann", "rossmann.de"),
    (r"dm[- ]drog", "dm", "dm.de"), (r"budni", "Budni", "budni.de"), (r"alnatura", "Alnatura", "alnatura.de"),
    (r"kaufland", "Kaufland", "kaufland.de"), (r"wolt", "Wolt", "wolt.com"), (r"lieferando", "Lieferando", "lieferando.de"),
    (r"db vertrieb|deutsche bahn", "Deutsche Bahn", "bahn.de"), (r"enterprise rent", "Enterprise", "enterprise.de"),
    (r"airbnb", "Airbnb", "airbnb.com"), (r"transavia", "Transavia", "transavia.com"), (r"sncf", "SNCF", "sncf-connect.com"),
    (r"trainline", "Trainline", "thetrainline.com"), (r"blablacar", "BlaBlaCar", "blablacar.de"),
    (r"rail europe", "Rail Europe", "raileurope.com"),     (r"telekom", "Telekom", "telekom.de"),
    (r"strato", "STRATO", "strato.de"), (r"mediamarkt|media markt", "MediaMarkt", "mediamarkt.de"),
    (r"cyberport", "Cyberport", "cyberport.de"), (r"galeria", "Galeria", "galeria.de"),
    (r"klarna", "Klarna", "klarna.com"), (r"libri", "Libri", "libri.de"), (r"ikea", "IKEA", "ikea.com"), (r"deutsche post", "Deutsche Post", "deutschepost.de"),
    (r"paypal", "PayPal", "paypal.com"), (r"sumup", "SumUp", "sumup.com"), (r"valve|steam", "Steam", "steampowered.com"),
    (r"nordsec|nordvpn", "NordVPN", "nordvpn.com"), (r"netflix", "Netflix", "netflix.com"), (r"spotify", "Spotify", "spotify.com"),
    (r"apple", "Apple", "apple.com"), (r"google", "Google", "google.com"), (r"openai", "OpenAI", "openai.com"),
    (r"anthropic|claude", "Anthropic", "anthropic.com"), (r"reservix", "Reservix", "reservix.de"), (r"eventim", "Eventim", "eventim.de"),
    (r"example ?fund|feeder", "Example Fund", "example.com"), (r"wiwin", "wiwin", "wiwin.de"),
    (r"gls gemeinschaftsbank|gls bank", "GLS Bank", "gls.de"), 
    (r"ryanair", "Ryanair", "ryanair.com"), (r"lufthansa", "Lufthansa", "lufthansa.com"),
    (r"easyjet", "easyJet", "easyjet.com"), (r"zalando", "Zalando", "zalando.de"), (r"decathlon", "Decathlon", "decathlon.de"),
    (r"uber eats", "Uber Eats", "ubereats.com"), (r"\buber\b", "Uber", "uber.com"), (r"flix", "FlixBus", "flixbus.de"),
    (r"dropbox", "Dropbox", "dropbox.com"), (r"microsoft", "Microsoft", "microsoft.com"), (r"adobe", "Adobe", "adobe.com"),
]
@lru_cache(maxsize=1)
def merchant_patterns() -> list[tuple[re.Pattern[str], str, str]]:
    """The extra merchants of config.json -> merchant_extra (checked first, so they override built-in brands), then the compiled MERCHANTS; built on first use (not at import)."""
    pats = [(re.compile(re.escape(k), re.I), v.get("name", k), v.get("domain", "")) for k, v in (setting("merchant_extra", {}) or {}).items()]
    return pats + [(re.compile(p, re.I), n, d) for p, n, d in MERCHANTS]      # own entries first: they override the built-in brands


def match_merchant(text: str | None) -> tuple[str, str] | None:
    """(display name, domain) of the first known merchant whose pattern matches `text`, else None."""
    for rx, n, d in merchant_patterns():
        if rx.search(text or ""):
            return n, d
    return None


def merchant_display(name: str) -> tuple[str, str]:
    """(shown name, domain) for a booking text: the known merchant name when one matches (and is short), else the text itself."""
    nm, dm = match_merchant(name) or (name, "")
    return (nm if dm and nm != name and len(nm) < 40 else name), dm


def merchant_and_domain(r: BookingRow) -> tuple[str, str]:
    """(display name, domain) for a booking: match on its label first, then on the counterparty."""
    raw = gls_parse.booking_label(r)
    return match_merchant(raw) or match_merchant(r["counterparty"]) or (raw, "")


categories.merchant_resolver = lambda r: merchant_and_domain(r)[0]      # lets your merchant rules (categories.set_user_rules) find the display name


def _merchant_sum() -> dict[str, Any]:
    """empty running total for one merchant: amount, number of bookings, amount per category, web domain"""
    return dict(v=0.0, n=0, cat=defaultdict(float), dom="")


class _FlowSums:
    """The running totals build_flow_model collects while it walks over the bookings (month keys look like '2024-05')."""

    def __init__(self) -> None:
        self.cats: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))   # category -> month -> spent
        self.inc: defaultdict[str, float] = defaultdict(float)        # month -> income
        self.exp: defaultdict[str, float] = defaultdict(float)        # month -> spending
        self.oo_in: defaultdict[str, float] = defaultdict(float)      # month -> one-off income
        self.oo_out: defaultdict[str, float] = defaultdict(float)     # month -> one-off spending
        self.inv: defaultdict[str, float] = defaultdict(float)        # month -> money moved into investments
        self.mer12: defaultdict[str, dict[str, Any]] = defaultdict(_merchant_sum)    # merchant -> totals, last 12 months
        self.merall: defaultdict[str, dict[str, Any]] = defaultdict(_merchant_sum)   # merchant -> totals, full history
        self.mer_cat: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))   # category -> merchant -> spent (12 months)
        self.sonst: defaultdict[str, float] = defaultdict(float)      # merchant -> spent in "Sonstiges" (12 months)
        self.mm: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))        # merchant -> month -> spent
        self.income_src: defaultdict[str, float] = defaultdict(float)  # merchant -> income (12 months)
        self.inc_mm: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))    # income source -> month -> income
        self.cat_mm: defaultdict[str, defaultdict[str, defaultdict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))   # category -> merchant -> month -> spent

    def add_income(self, r: BookingRow, mk: str, recent: bool) -> None:
        self.inc[mk] += r["amount"]
        src = merchant_and_domain(r)[0]
        self.inc_mm[src][mk] += r["amount"]
        if recent:
            self.income_src[src] += r["amount"]

    def add_expense(self, r: BookingRow, mk: str, recent: bool) -> None:
        c = classify(r)
        v = -r["amount"]
        self.cats[c][mk] += v
        self.exp[mk] += v
        name, dom = merchant_and_domain(r)
        self.mm[name][mk] += v
        self.cat_mm[c][name][mk] += v
        for tgt in ([self.merall] + ([self.mer12] if recent else [])):
            m = tgt[name]
            m["v"] += v; m["n"] += 1; m["cat"][c] += v; m["dom"] = m["dom"] or dom
        if recent:
            self.mer_cat[c][name] += v
            if c == SONSTIGES:
                self.sonst[name] += v

    def spenders(self, src: dict[str, Any], n: int, months: list[str]) -> list[Spender]:
        """the n biggest merchants of `src` with their monthly spending"""
        out: list[Spender] = []
        for k, m in sorted(src.items(), key=lambda kv: -kv[1]["v"])[:n]:
            out.append(Spender(n=k, v=round2(m["v"]), tx=m["n"], cat=max(m["cat"], key=m["cat"].get), dom=m["dom"],
                            m=[round2(self.mm[k].get(x, 0)) for x in months]))
        return out


def _sum_bookings(rows: list[BookingRow], big: float) -> _FlowSums:
    """Walk over all bookings once and collect the totals (own transfers and card settlements are skipped)."""
    own = OwnAccounts(rows)
    cut12 = today() - dt.timedelta(days=365)
    t = _FlowSums()
    for r, mk, kind in cash_flow_events(rows, own):
        if kind == "invest":
            t.inv[mk] += -r["amount"]          # buying/selling investments is not spending
            continue
        if abs(r["amount"]) >= big:
            (t.oo_in if r["amount"] > 0 else t.oo_out)[mk] += abs(r["amount"])
        if kind == "income":
            t.add_income(r, mk, r["date"] >= cut12)
        else:
            t.add_expense(r, mk, r["date"] >= cut12)
    return t


def _top(totals: dict[str, float], n: int) -> list[NameValue]:
    """the n biggest entries as [{n: name, v: amount}]"""
    return [NameValue(n=k, v=round2(v)) for k, v in sorted(totals.items(), key=lambda kv: -kv[1])[:n]]


def _monthly_top(src: dict[str, dict[str, float]], months: list[str], n: int) -> list[MonthlySeries]:
    """the n biggest names (over the whole history) with their amount in every month of `months`"""
    best = sorted(src.items(), key=lambda kv: -sum(kv[1].values()))[:n]
    return [MonthlySeries(n=k, m=[round2(v.get(m, 0)) for m in months]) for k, v in best]


def build_flow_model(rows: list[BookingRow]) -> FlowModel | None:
    """Full-history monthly income / expenses by category (own classifier). One-offs are INCLUDED."""
    if not rows:
        return None
    first = min(r["date"] for r in rows)
    months = mrange(month_key(first), now_month())
    big = oneoff_threshold()
    t = _sum_bookings(rows, big)
    order = sorted(t.cats, key=lambda c: (c == SONSTIGES, -sum(t.cats[c].values())))
    income = [round2(t.inc.get(m, 0)) for m in months]
    expense = [round2(t.exp.get(m, 0)) for m in months]
    return FlowModel(
        months=months,
        cats={c: [round2(t.cats[c].get(m, 0)) for m in months] for c in order},
        income=income,
        expense=expense,
        oneoff_in=[round2(t.oo_in.get(m, 0)) for m in months],
        oneoff_out=[round2(t.oo_out.get(m, 0)) for m in months],
        invested=[round2(t.inv.get(m, 0)) for m in months],
        top_merchants={c: _top(t.mer_cat[c], 8) for c in order},
        top_spenders=dict(y1=t.spenders(t.mer12, 25, months), all=t.spenders(t.merall, 25, months)),
        income_sources=_top(t.income_src, 8),
        income_by_source=_monthly_top(t.inc_mm, months, 10),
        cat_merchants={c: _monthly_top(t.cat_mm[c], months, 10) for c in order},
        oneoff_threshold=big,
        sonstiges_top=_top(t.sonst, 60),
        savings=[round2(i - e) for i, e in zip(income, expense)],
    )


def spending_rows(rows: list[BookingRow]) -> list[SpendingRow]:
    """Real spending only, for unusual.find_unusual(): no income, internal moves, card settlements or investments
    (same filters as build_flow_model)."""
    own = OwnAccounts(rows)
    out: list[SpendingRow] = []
    for r in rows:
        if r["amount"] >= 0 or own.flow_kind(r) != "flow":
            continue
        out.append(SpendingRow(date=r["date"].isoformat(), merchant=merchant_and_domain(r)[0], amount=r["amount"], category=classify(r)))
    return out


def balance_history(rows: list[BookingRow]) -> BalanceHistory | None:
    """month-end balance per account kind, full history on its own month axis."""
    if not rows:
        return None
    first = min(r["date"] for r in rows)
    months = mrange(month_key(first), now_month())
    return gls_block.month_end_balances(rows, months, ACCOUNT_KINDS)

"""Bank bookings and the GLS block of data.json: account kinds, BookingRow, spending, flow model, coverage, PayPal summary."""
from __future__ import annotations
from typing import Any, Literal, TypedDict, get_args
import datetime as dt


Kind = Literal["giro", "tages", "card", "shares"]      # GLS account kinds


ACCOUNT_KINDS: tuple[Kind, ...] = get_args(Kind)       # all kinds in display order: giro, tages, card, shares


CASH_KINDS: tuple[Kind, ...] = ("giro", "tages", "card")      # accounts that hold spendable money (no bank shares)


FLOW_KINDS: tuple[Kind, ...] = ("giro", "card")                # accounts whose bookings are income or spending


class BookingRow(TypedDict):
    iban: str
    account: str
    date: dt.date
    counterparty: str
    cp_iban: str
    typ: str
    purpose: str
    amount: float
    balance: float | None
    cat: str
    kind: Kind


class SpendingRow(TypedDict):
    """one real spending booking as bookings.spending_rows() lists it (amount < 0 = money out)"""
    date: str
    merchant: str
    amount: float
    category: str


class Coverage(TypedDict):
    """one account of db_queries.coverage(): its first / last booking day, booking count, age and the months without any booking"""
    iban: str
    account: str | None
    kind: str | None
    first: str
    last: str
    n: int
    age_days: int
    gap_months: list[str]


class NameValue(TypedDict):
    n: str
    v: float


class Spender(TypedDict):
    """one merchant of FlowModel.top_spenders: total, number of bookings, main category, web domain and the amount per month"""
    n: str
    v: float
    tx: int
    cat: str
    dom: str
    m: list[float]


class MonthlySeries(TypedDict):
    """a name with one amount per month of the flow model's `months` (positive amounts)"""
    n: str
    m: list[float]


class FlowModel(TypedDict):
    """what bookings.build_flow_model() returns: one value per month of `months` in every list (money amounts are positive)"""
    months: list[str]
    cats: dict[str, list[float]]
    income: list[float]
    expense: list[float]
    oneoff_in: list[float]
    oneoff_out: list[float]
    invested: list[float]
    top_merchants: dict[str, list[NameValue]]
    top_spenders: dict[str, list[Spender]]
    income_sources: list[NameValue]
    income_by_source: list[MonthlySeries]      # v1.15: the biggest income sources with their monthly amounts (for the cash-flow pop-up)
    cat_merchants: dict[str, list[MonthlySeries]]      # v1.15: per category the biggest payees with their monthly amounts
    oneoff_threshold: float
    sonstiges_top: list[NameValue]
    savings: list[float]


class PaypalInfo(TypedDict):
    """the PayPal block: newest usable balance (None when missing or too old), its date and how many PayPal 'Download*.csv' exports the folder holds"""
    balance: float | None
    asof: str | None
    files: int


class GlsAccount(TypedDict):
    iban_tail: str
    name: str
    kind: Kind
    balance: float | None
    last_booking: str | None


class _GlsFlowRequired(TypedDict):
    months: list[str]
    income: list[float]
    expense: list[float]
    oneoff_in: list[float]
    oneoff_out: list[float]
    invest_out: list[float]
    invest_in: list[float]
    oneoff_threshold: float
    net: list[float]


class GlsFlow(_GlsFlowRequired, total=False):
    avg12_income: float           # added by totals.apply_flow_kpis
    avg12_expense: float
    avg3_expense: float
    invested12: float


class CategoryTotal(TypedDict):
    c: str
    v: float


class GlsCategories(TypedDict):
    m3: list[CategoryTotal]
    m12: list[CategoryTotal]


class RecurringCost(TypedDict):
    label: str
    amount: float
    months: int


class RecentBooking(TypedDict, total=False):
    """one booking of the 'recent' / 'all_bookings' lists (src is only on the recent ones; lg is added by apply_flow_kpis)"""
    d: str | None
    n: str
    v: float
    c: str
    src: str
    lg: str


class LargeBooking(TypedDict):
    d: str | None
    n: str
    v: float
    c: str


class _BalanceHistoryRequired(TypedDict):
    months: list[str]


class BalanceHistory(_BalanceHistoryRequired, total=False):
    """month-end balance per account kind (a kind is missing when the block does not cover it)"""
    giro: list[float | None]
    tages: list[float | None]
    card: list[float | None]
    shares: list[float | None]


class _GlsBlockRequired(TypedDict):
    accounts: list[GlsAccount]
    flow: GlsFlow
    categories: GlsCategories
    recurring: list[RecurringCost]
    cash_history: BalanceHistory
    recent: list[RecentBooking]
    large: list[LargeBooking]
    last_booking: str | None


class GlsBlock(_GlsBlockRequired, total=False):
    """the 'gls' block of data.json (gls_block.build_gls_block); apply_flow_kpis and apply_runway add the last four keys"""
    all_bookings: list[RecentBooking]       # only passes through to apply_flow_kpis, which removes it again
    income_sources: list[NameValue]
    merchants: list[Spender]
    bookings: dict[str, list[list[Any]]]
    runway_months: float | None

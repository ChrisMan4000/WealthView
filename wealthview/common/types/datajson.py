"""The blocks of data.json and the DataJson document itself (refresh.py writes it, the .js files read it)."""
from __future__ import annotations
from typing import Any, TypedDict
from .bookings import BalanceHistory, Coverage, FlowModel, GlsBlock, PaypalInfo
from .depot import AssetGroup, CryptoBlock, Depot
from .status import Alert, SourceStatus, SyncReport


NwSeries = dict[str, list[float | None]]      # asset class -> value per month on the shared month axis


class _TotalsRequired(TypedDict):
    giro: float
    tages: float
    card: float
    shares: float
    paypal: float | None


class Totals(_TotalsRequired, total=False):
    """account balances (analysis.totals.account_totals); compute_totals adds the asset groups, liabilities, net and tax"""
    assets: float
    groups: list[AssetGroup]
    liabilities: float
    net: float
    tax: float
    net_after_tax: float


class NwxSeries(TypedDict):
    """gross wealth, loan balance and net wealth per month"""
    gross: list[float]
    loan: list[float]
    net: list[float]


class ExampleFundFund(TypedDict, total=False):
    name: str
    commitments: float
    paid_in: float
    distributions: float
    unfunded: float
    nav: float
    tvpi: float
    dpi: float
    rvpi: float
    net_irr: float
    term_end: str
    prev: dict[str, Any]


class _ExampleFundPersonalRequired(TypedDict):
    nav: float
    paid_in: float


class ExampleFundPersonal(_ExampleFundPersonalRequired, total=False):
    commitment: float
    unfunded: float
    nav_prev_quarter: float
    ownership_pct: float
    dist_est: float
    tvpi_est: float


class ExampleFundCompany(TypedDict, total=False):
    slug: str
    name: str
    fair_value: float
    look_through: float
    web: str


class _ExampleFundRequired(TypedDict):
    report_year: int
    report_q: int
    fund: ExampleFundFund
    personal: ExampleFundPersonal
    companies: list[ExampleFundCompany]


class ExampleFund(_ExampleFundRequired, total=False):
    """the Example Fund block (examplefund.json plus what loaders.load_examplefund adds)"""
    source: str
    portfolio_url: str
    site: str
    newest_report_file: str | None
    update_available: bool
    title: str


class Wiwin(TypedDict, total=False):
    invested: float
    since: str


class Apartment(TypedDict, total=False):
    """the apartment block: the config.json settings plus what models.apartment_model computes"""
    purchase_date: str
    purchase_price: float
    sqm: float
    current_value: float | None
    benchmark: dict[str, float]
    benchmark2: dict[str, float]
    use_estimate: bool
    sources: list[Any]
    series: list[float | None]
    series2: list[float | None]
    estimate: float
    purchase_per_sqm: float
    estimate_per_sqm: float
    gain: float
    gain_pct: float
    value_used: float


class Loan(TypedDict):
    """the family loan (models.loan_model)"""
    lender: str
    principal: float
    monthly: float
    start: str
    balance: float
    repaid: float
    months_paid: int
    months_left: int | None
    payoff: str
    series: list[float]


class TaxEstimate(TypedDict):
    """models.tax_model: the tax if everything were sold today"""
    rate_pct: float
    allowance: float
    securities_gain: float
    pe_gain: float
    taxable: float
    tax: float
    flat_tax: float
    tariff_tax: float
    method: str
    grundfreibetrag: float
    tax_free_headroom: float
    crypto_note: str
    real_estate_note: str
    note: str


class IncomeItem(TypedDict):
    n: str
    wkn: str
    v: float


class _IncomeEstimateRequired(TypedDict):
    items: list[IncomeItem]
    covered: int
    total_positions: int


class IncomeEstimate(_IncomeEstimateRequired, total=False):
    yearly: float
    monthly: float
    note: str


class ReminderItem(TypedDict, total=False):
    key: str
    source: str
    what_to_download: str
    where: str
    folder_key: str
    folder: str
    pattern: str
    schedule: str
    latest: str | None
    due: bool
    days_old: int | None
    accounts: list[dict[str, Any]]


class Reminders(TypedDict):
    """data["reminders"]: which sources need fresh files (data/ingest/sources.py)"""
    month: str
    any_due: bool
    items: list[ReminderItem]


class UnusualFinding(TypedDict):
    date: str
    merchant: str
    amount: float
    reasons: list[str]
    detail: str


class AnalyticsResult(TypedDict):
    """data["analytics"] (analytics.build_analytics): the wealth-manager sections; each section is a dict the page reads by key"""
    asof: str
    first_investment: dict[str, str]
    performance: dict[str, Any]
    risk: dict[str, Any]
    exposure: dict[str, Any]
    allocation: dict[str, Any]
    liquidity: dict[str, Any]
    private_equity: dict[str, Any]
    costs: dict[str, Any]
    tax: dict[str, Any]
    real: dict[str, Any]


class AnalyticsError(TypedDict):
    """data["analytics"] when the analytics could not be computed (shown on the page)"""
    error: str


class DbBlock(TypedDict):
    """data["db"]: what the page shows about the database (System status / coverage)"""
    file: str
    size_kb: int | None
    counts: dict[str, int | str | None]
    sync: SyncReport | None
    last_import: Any
    coverage: list[Coverage]


class Insights(TypedDict):
    """data["insights"] (insights.build): history-based observations; each section is a dict or list the page reads by key"""
    version: int
    curve: Any
    changes: Any
    saved_vs_market: Any
    spend_vs_norm: Any
    yoy: Any
    recurring: Any
    digest: Any


class DataJson(TypedDict, total=False):
    """The root of data.json. refresh.main() builds most keys, finish_data adds analytics / unusual / db / insights / tax and
    refresh.quick_main() patches the stored document (version, quick, reminders ...). Keys are optional because the quick
    refresh reads an older file back and the demo data has fewer."""
    mode: str
    generated: str
    owner: str
    version: str
    quick: bool
    axis: list[str]
    totals: Totals
    nw: NwSeries
    nwx: NwxSeries
    gls: GlsBlock | None
    flows: FlowModel | None
    balances: BalanceHistory | None
    depot: Depot | None
    crypto: CryptoBlock | None
    examplefund: ExampleFund | None
    assets: dict[str, Any] | None
    paypal: PaypalInfo
    wiwin: Wiwin
    apartment: Apartment
    loan: Loan | None
    income_est: IncomeEstimate
    sources: dict[str, SourceStatus]
    alerts: list[Alert]
    reminder: Any
    reminders: Reminders | None
    apartment_sources: list[Any]
    tax: TaxEstimate
    apartment_sale: dict[str, Any]
    analytics: AnalyticsResult | AnalyticsError
    unusual: list[UnusualFinding]
    db: DbBlock | None
    insights: Insights | None

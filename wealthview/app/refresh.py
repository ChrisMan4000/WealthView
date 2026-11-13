"""
WEALTHVIEW - data refresh (READ-ONLY on your source folders).

Reads GLS Bank / PayPal / Example Fund files, asks Coinbase and Yahoo Finance for live
data, and writes data.json (into data/) and src_logos.js (main folder) - nothing outside the WealthView folder.
This module only runs the stages in order (full refresh: main, light refresh: quick_main); the work itself is in analysis/, data/ and refresh_stages.py.
Run by hand:   python refresh.py          (the dashboard's REFRESH button runs it too)
"""
from __future__ import annotations
import json, sqlite3, sys, traceback
from typing import Any, Callable, NamedTuple
from ..common import config
from ..common.bootstrap import bootstrap
from ..common.fileio import write_atomic
from ..common.paths import data_path, version
from ..common.profile import Profile, load_profile
from ..common.runcontext import RunContext, run_stage
from ..common.timeutil import axis, now, today
from ..common.types.bookings import BalanceHistory, BookingRow, Coverage, FlowModel, GlsBlock, PaypalInfo
from ..common.types.datajson import Apartment, DataJson, IncomeEstimate, Loan, NwSeries, Reminders, Totals, ExampleFund
from ..common.types.depot import CryptoBlock, Depot
from ..common.types.status import SourceStatus, SyncReport
from ..data.finance import assets as typed_assets, gls_block
from ..data.finance.bookings import balance_history, build_flow_model, spending_rows
from ..data.finance.models import apartment_model, loan_model, nw_series
from ..data.finance.positions import enrich_crypto, enrich_crypto_cost, income_estimate
from ..data.ingest import db_queries, db_schema, loaders
from ..data.ingest import sources as reminder_sources
from ..data.ingest.logo_fetch import fetch_logos
from ..data.ingest.paypal import load_paypal_preferring_db, paypal_best_from_db
from ..data.ingest.quotes import live_prices
from ..analysis import insights, quick, unusual
from . import refresh_stages
from .refresh_stages import DB_ERRORS
from ..analysis.alerts import dedupe_alerts, raise_alerts
from ..analysis.analytics_run import compute_analytics
from ..analysis.totals import account_totals, apply_flow_kpis, apply_runway, compute_totals, gross_and_net, logo_candidates, logo_extras


def build_sources(ctx: RunContext, depot: Depot | None, apartment: bool = True) -> dict[str, SourceStatus]:
    """Per-source status for the dashboard (copy of ctx.status plus live flags; the apartment line only while that module is on)."""
    status = ctx.snapshot()
    off: SourceStatus = {"state": "off", "msg": ""}
    status["gls"]["live"] = False
    depot_status = status.get("depot", off).copy()
    depot_status["live"] = bool(depot and depot.get("n_live"))
    depot_status["n_live"] = depot.get("n_live") if depot else None
    depot_status["n_total"] = depot.get("n_total") if depot else None
    status["depot"] = depot_status
    coinbase_status = status.get("coinbase", off).copy()
    coinbase_status["live"] = coinbase_status["state"] == "ok"
    status["coinbase"] = coinbase_status
    if apartment:
        status["apartment"] = {"state": "ok", "msg": "benchmark model", "live": False, "model": True}
    return status


def finish_data(ctx: RunContext, conn: sqlite3.Connection | None, sync_rep: SyncReport | None, rows: list[BookingRow], flows: FlowModel | None, cov: list[Coverage], data: DataJson) -> None:
    """Totals, analytics, unusual bookings, snapshot, spending tables, db block and insights."""
    compute_totals(data)
    compute_analytics(ctx, data, external=True)
    data["unusual"] = run_stage(ctx, "refresh.finish_data.unusual", lambda: unusual.find_unusual(spending_rows(rows), today().isoformat(), config.cfg_value("unusual")),
                                [], alert=True, msg="Unusual bookings could not be computed: ")
    refresh_stages.record_snapshot(ctx, conn, data)
    if conn:
        def save_spending() -> None:
            db_queries.store_spending(conn, spending_rows(rows))
            db_queries.store_monthly(conn, flows)
        run_stage(ctx, "refresh.finish_data.spending", save_spending, None,
                  alert=True, msg="Could not save spending to the database: ", errors=(sqlite3.Error, KeyError, ValueError, TypeError))
    data["db"] = refresh_stages.db_block(conn, sync_rep, cov)
    data["insights"] = run_stage(ctx, "refresh.finish_data.insights", lambda: insights.build(conn, data, rows, today(), spending_rows(rows)) if conn else None,
                                 None, alert=True, msg="Insights could not be computed: ")


def build_reminders(ctx: RunContext, conn: sqlite3.Connection | None, examplefund: ExampleFund | None, examplefund_on: bool = True) -> Reminders | None:
    """Which sources need fresh files (see data/ingest/sources.py); never stops the refresh. Without the Example Fund module there is no Example Fund reminder."""
    rem = run_stage(ctx, "refresh.build_reminders", lambda: reminder_sources.collect(conn, examplefund, today()), None)
    if rem and not examplefund_on:
        rem["items"] = [i for i in rem["items"] if i.get("key") != "examplefund"]
        rem["any_due"] = any(i.get("due") for i in rem["items"])
    return rem


def write_data(data: DataJson) -> None:
    write_atomic(data_path("data.json"), json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def write_outputs(data: DataJson, flows: FlowModel | None) -> None:
    """data.json plus the classifier helper report (not shown in the dashboard)."""
    write_data(data)
    if flows:
        write_atomic(data_path("sonstiges_report.txt"), "\n".join(f"{x['v']:9.0f}  {x['n']}" for x in flows["sonstiges_top"]))


class Run:
    """Everything the stages of the full refresh pass on to each other. A value exists only after the stage that provides it has run
    (reading it earlier raises AttributeError, so a wrong stage order cannot go unnoticed)."""
    ctx: RunContext
    profile: Profile
    conn: sqlite3.Connection | None = None
    sync_rep: SyncReport | None
    rows: list[BookingRow]
    gls: GlsBlock | None
    flows: FlowModel | None
    balances: BalanceHistory | None
    depot: Depot | None
    crypto: CryptoBlock | None
    examplefund: ExampleFund | None
    paypal: PaypalInfo
    apartment: Apartment | None
    loan: Loan | None
    assets: dict[str, Any] | None
    totals: Totals
    giro: float
    tages: float
    income: IncomeEstimate
    nw: NwSeries
    loan_series: list[float]
    gross: list[float]
    net: list[float]
    cov: list[Coverage]
    sources: dict[str, SourceStatus]
    data: DataJson

    def __init__(self) -> None:
        self.ctx = RunContext()
        self.profile = load_profile()       # which optional modules and which tax country this install uses (legacy: everything on, DE)

    def module(self, name: str) -> bool:
        """True when the optional module (examplefund, wiwin, loan, apartment) is on in the profile."""
        return self.profile.modules.get(name, True)


class Stage(NamedTuple):
    """One step of the full refresh. needs / provides name the Run values it reads / sets (see STAGES)."""
    name: str
    run: Callable[[Run], None]
    needs: tuple[str, ...]
    provides: tuple[str, ...]


def stage_open_db(r: Run) -> None:
    r.conn, r.sync_rep = refresh_stages.open_db(r.ctx)
    refresh_stages.load_category_rules(r.ctx, r.conn)       # your saved corrections apply from here on


def stage_bookings(r: Run) -> None:
    r.rows = refresh_stages.load_rows(r.ctx, r.conn)


def stage_gls_and_flows(r: Run) -> None:
    r.gls = gls_block.build_gls_block(r.rows)
    r.flows = build_flow_model(r.rows)
    r.balances = balance_history(r.rows)


def stage_depot(r: Run) -> None:
    r.depot = refresh_stages.load_depot_with_trades(r.ctx, r.rows, r.conn)


def stage_save_trades(r: Run) -> None:
    refresh_stages.save_trades(r.ctx, r.conn, r.rows)


def stage_crypto(r: Run) -> None:
    r.crypto = run_stage(r.ctx, "refresh.stage_crypto", lambda: loaders.load_coinbase(r.ctx), None, status="coinbase", msg="Coinbase could not be read: ")
    conn = r.conn
    if not r.crypto and conn:       # no Coinbase API / cache: use the buys and sells the automatic reader stored
        r.crypto = run_stage(r.ctx, "refresh.stage_crypto_db", lambda: loaders.load_crypto_db(r.ctx, conn), None, status="coinbase", msg="crypto from the database could not be read: ")
    if r.crypto:
        enrich_crypto(r.crypto)
        enrich_crypto_cost(r.crypto)


def stage_examplefund(r: Run) -> None:
    r.examplefund = loaders.load_examplefund(r.ctx) if r.module("examplefund") else None


def stage_paypal(r: Run) -> None:
    conn = r.conn
    best = run_stage(r.ctx, "refresh.stage_paypal", lambda: paypal_best_from_db(conn) if conn else None, None, status="database",
                     msg="PayPal could not be read from the database: ", errors=DB_ERRORS)
    r.paypal = load_paypal_preferring_db(r.ctx, best)


def stage_models(r: Run) -> None:
    if r.module("apartment"):
        r.apartment = apartment_model()
        r.apartment["use_estimate"] = config.section("apartment").get("use_estimate", True)
    else:
        r.apartment = None
    r.loan = loan_model() if r.module("loan") else None


def stage_assets(r: Run) -> None:
    """The house, loans, funds and other investments typed in (v1.20) plus typed bank balances; None when there are none."""
    conn = r.conn
    r.assets = run_stage(r.ctx, "refresh.stage_assets", lambda: typed_assets.build_assets_block(conn, today()) if conn else None, None,
                         status="database", msg="your typed assets could not be read: ", errors=DB_ERRORS)


def stage_account_totals(r: Run) -> None:
    r.totals, r.giro, r.tages = account_totals(r.gls, r.paypal)


def stage_income(r: Run) -> None:
    r.income = income_estimate(r.depot, r.tages)


def stage_flow_kpis(r: Run) -> None:
    apply_flow_kpis(r.gls, r.flows)


def stage_runway(r: Run) -> None:
    apply_runway(r.gls, r.giro, r.tages)


def stage_logos(r: Run) -> None:
    coins = [h["currency"] for h in (r.crypto or {}).get("holdings", []) if (h.get("eur") or 0) > 0.5]
    run_stage(r.ctx, "refresh.stage_logos", lambda: fetch_logos(r.ctx, r.depot["positions"] if r.depot else [], logo_extras(r.flows, r.gls), coins, candidates=logo_candidates(r.flows, r.gls)), None,
              status="logos", msg="logos could not be built: ")


def stage_net_worth(r: Run) -> None:
    r.nw = nw_series(r.depot, r.crypto, r.examplefund, r.apartment, r.balances, r.paypal, wiwin=r.module("wiwin"))
    old_loan = r.loan["series"] if r.loan else [0] * len(axis())
    r.loan_series = typed_assets.add_to_nw(r.nw, old_loan, r.assets, axis())      # type: ignore[arg-type]      # the typed house, funds and loans join the series
    r.gross, r.net = gross_and_net(r.nw, r.loan_series, len(axis()))


def stage_coverage(r: Run) -> None:
    conn = r.conn
    r.cov = run_stage(r.ctx, "refresh.stage_coverage", lambda: db_queries.coverage(conn, today()) if conn else [], [], status="database",
                      msg="database coverage could not be read: ", errors=DB_ERRORS)


def stage_alerts(r: Run) -> None:
    raise_alerts(r.ctx, r.sync_rep, r.rows, r.depot, r.gls, r.flows, r.giro, r.cov)


def stage_sources(r: Run) -> None:
    r.sources = build_sources(r.ctx, r.depot, apartment=r.module("apartment"))


MODULE_BLOCKS = {"examplefund": ("examplefund",), "wiwin": ("wiwin",), "loan": ("loan",), "apartment": ("apartment", "apartment_sources", "apartment_sale")}


def stage_assemble(r: Run) -> None:
    """Puts all blocks together into the data.json document (the alerts must be complete by now)."""
    cfg = config.load_config()
    r.data = DataJson(
        mode="real", generated=now().isoformat(timespec="seconds"), owner=cfg.get("display_name", "WealthView user"),
        axis=axis(), totals=r.totals, nw=r.nw, nwx=dict(gross=r.gross, loan=r.loan_series, net=r.net), gls=r.gls, flows=r.flows, balances=r.balances,
        depot=r.depot, crypto=r.crypto, examplefund=r.examplefund, paypal=r.paypal, wiwin=cfg.get("wiwin"), apartment=r.apartment, loan=r.loan, income_est=r.income,      # type: ignore[typeddict-item]
        sources=r.sources, alerts=r.ctx.alerts, reminder=cfg.get("reminder"), reminders=build_reminders(r.ctx, r.conn, r.examplefund, r.module("examplefund")),
        apartment_sources=(cfg.get("apartment") or {}).get("sources", []),
    )
    if r.assets:
        r.data["assets"] = r.assets      # only when something was typed in or found: an install without typed assets keeps its data.json as it was
    for module, keys in MODULE_BLOCKS.items():       # a module that is off leaves its blocks out of data.json altogether
        if not r.module(module):
            for k in keys:
                r.data.pop(k, None)     # type: ignore[misc]


def stage_finish(r: Run) -> None:
    finish_data(r.ctx, r.conn, r.sync_rep, r.rows, r.flows, r.cov, r.data)
    # finish_data can change source status lines and add alerts after stage_sources took its snapshot: take it again, dedupe again
    r.sources = build_sources(r.ctx, r.depot, apartment=r.module("apartment"))
    r.data["sources"] = r.sources
    dedupe_alerts(r.ctx)


def stage_write(r: Run) -> None:
    write_outputs(r.data, r.flows)
    if r.conn:
        r.conn.close()


# The full refresh, in this order. "needs" are the Run values a stage reads, "provides" the ones it sets; check_stage_order() (run by the
# tests) fails when a stage needs something no earlier stage provides. Values that are changed in place get a name of their own
# (flow_kpis, runway, trades_saved) so that later stages can depend on them.
STAGES: list[Stage] = [
    Stage("open the database and import new files", stage_open_db, (), ("conn", "sync_rep")),
    Stage("read the GLS bookings", stage_bookings, ("conn",), ("rows",)),
    Stage("GLS block, flow model, balance history", stage_gls_and_flows, ("rows",), ("gls", "flows", "balances")),
    Stage("depot with live quotes and trades", stage_depot, ("rows", "conn"), ("depot",)),
    Stage("save the trades", stage_save_trades, ("conn", "rows"), ("trades_saved",)),
    Stage("Coinbase", stage_crypto, ("conn",), ("crypto",)),
    Stage("Example Fund", stage_examplefund, (), ("examplefund",)),
    Stage("PayPal", stage_paypal, ("conn",), ("paypal",)),
    Stage("apartment and loan models", stage_models, (), ("apartment", "loan")),
    Stage("typed assets: house, loans, funds, other", stage_assets, ("conn",), ("assets",)),
    Stage("account totals", stage_account_totals, ("gls", "paypal"), ("totals", "giro", "tages")),
    Stage("income estimate", stage_income, ("depot", "tages"), ("income",)),
    Stage("12-month KPIs from the flow model", stage_flow_kpis, ("gls", "flows"), ("flow_kpis",)),
    Stage("cash runway", stage_runway, ("gls", "giro", "tages"), ("runway",)),
    Stage("merchant and position logos", stage_logos, ("depot", "crypto", "flows", "gls", "flow_kpis"), ("logos",)),
    Stage("net worth series", stage_net_worth, ("depot", "crypto", "examplefund", "apartment", "loan", "assets", "balances", "paypal"),
          ("nw", "loan_series", "gross", "net")),
    Stage("database coverage", stage_coverage, ("conn",), ("cov",)),
    Stage("dashboard alerts", stage_alerts, ("sync_rep", "rows", "depot", "gls", "flows", "giro", "cov", "flow_kpis"), ("alerts",)),
    Stage("source status lines", stage_sources, ("depot",), ("sources",)),
    Stage("assemble data.json", stage_assemble, ("totals", "nw", "loan_series", "gross", "net", "gls", "flows", "balances", "depot", "crypto",
                                                 "examplefund", "assets", "paypal", "apartment", "loan", "income", "sources", "alerts", "runway", "logos"), ("data",)),
    Stage("totals, analytics, insights", stage_finish, ("conn", "sync_rep", "rows", "flows", "cov", "data"), ("finished",)),
    Stage("write data.json", stage_write, ("data", "flows", "finished", "trades_saved"), ("written",)),
]


def check_stage_order(stages: list[Stage], start: tuple[str, ...] = ()) -> None:
    """Raises ValueError when a stage needs a value that no earlier stage (or `start`) provides."""
    have = set(start)
    for st in stages:
        missing = [n for n in st.needs if n not in have]
        if missing:
            raise ValueError(f"stage '{st.name}' needs {', '.join(missing)} before it runs")
        have.update(st.provides)


def main() -> None:
    """Full refresh: run the STAGES in order (read every source, build data.json, write it)."""
    r = Run()
    for st in STAGES:
        st.run(r)
    t = r.data["totals"]
    print(f"OK {now():%Y-%m-%d %H:%M} gross={t['assets']:,.0f} net={t['net']:,.0f} after-tax={t['net_after_tax']:,.0f} EUR  " +
          ", ".join(f"{k}:{v.get('state')}" for k, v in r.sources.items()))


def quick_main() -> None:
    """Light refresh (every 5 min): Coinbase balances + live prices -> patches data.json in place."""
    ctx = RunContext()
    data: DataJson = json.loads((data_path("data.json")).read_text("utf-8"))
    quick.quick_crypto(ctx, data)
    quick.quick_depot(data, live_prices(data, crypto=False))
    compute_totals(data)
    quick.quick_nwx(data)
    data["generated"] = now().isoformat(timespec="seconds")
    compute_analytics(ctx, data, external=False)
    data["version"] = version()
    data["quick"] = True

    def snapshot_and_reminders() -> None:
        qconn = db_schema.connect(data_path(db_schema.DB_NAME))
        try:
            refresh_stages.record_snapshot(ctx, qconn, data)
            data["reminders"] = build_reminders(ctx, qconn, data.get("examplefund")) or data.get("reminders")
        finally:
            qconn.close()
    run_stage(ctx, "refresh.quick_main", snapshot_and_reminders, None, errors=(sqlite3.Error, OSError))
    write_data(data)
    print(f"QUICK OK {now():%H:%M} gross={data['totals']['assets']:,.0f}")


def run_cli(argv: list[str]) -> int:
    """Entry point: --quick for the light refresh, otherwise the full one. Returns the process exit code."""
    try:
        bootstrap()
        quick_main() if "--quick" in argv else main()
    except Exception:       # broad on purpose: last-resort handler, writes refresh_error.log instead of dying silently
        text = traceback.format_exc()
        write_atomic(data_path("refresh_error.log"), now().isoformat() + "\n" + text)
        sys.stderr.write(text)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv))

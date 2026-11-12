"""Dashboard alerts: low balance, runway, data gaps, imports, unclassified spending; de-duplicated, warnings first."""
from __future__ import annotations

from ..common import config
from ..data.finance.categories import SONSTIGES
from ..common.runcontext import RunContext
from .gaps import data_gaps, gap_messages
from ..common.types.bookings import BookingRow, Coverage, FlowModel, GlsBlock
from ..common.types.depot import Depot
from ..common.types.status import Alert, SyncReport


def threshold_alerts(ctx: RunContext, g: GlsBlock | None, giro: float) -> None:
    """Low giro balance warning. Without a GLS block giro is 0, so nothing is checked then (no false alarm)."""
    if g:
        th = config.setting("thresholds", {})
        limit = th.get("giro_min_eur")
        if limit is not None and giro < limit:
            ctx.add_alert("warn", f"Giro balance {giro:,.0f} EUR is below your {limit:,} EUR threshold.")


def import_alerts(ctx: RunContext, sync_rep: SyncReport | None) -> None:
    """Info/warn alerts about files that were imported into the database."""
    if sync_rep:
        nb = sync_rep["new_bookings"] + sync_rep["new_paypal"]
        if sync_rep["new_files"] and nb:
            ctx.add_alert("info", f"Imported {sync_rep['new_bookings']} new bookings and {sync_rep['new_paypal']} PayPal transactions from {len(sync_rep['new_files'])} new file(s).")
        for e in sync_rep["errors"][:3]:
            ctx.add_alert("warn", "Import: " + e)


def dedupe_alerts(ctx: RunContext) -> None:
    """Drops alerts with the same text (ignoring case and extra spaces); warnings first."""
    seen: set[str] = set()
    ded: list[Alert] = []
    for a_ in ctx.alerts:
        k = " ".join(a_["text"].split()).lower()
        if k not in seen:
            seen.add(k)
            ded.append(a_)
    ctx.alerts[:] = sorted(ded, key=lambda a_: a_["level"] != "warn")


def sonstiges_alert(ctx: RunContext, flows: FlowModel | None) -> None:
    """Hint to add category rules while too much spending is still unclassified."""
    if not flows:
        return
    cats = flows["cats"]
    sc = cats.get(SONSTIGES)
    if sc:
        share = sum(sc[-12:]) / max(1, sum(sum(v[-12:]) for v in cats.values()))
        if share > 0.12:
            ctx.add_alert("info", f"{share*100:.0f}% of last-12-month spending is still 'Sonstiges' - add rules under category_rules in config.json.")


def raise_alerts(ctx: RunContext, sync_rep: SyncReport | None, rows: list[BookingRow], depot: Depot | None,
                 g: GlsBlock | None, flows: FlowModel | None, giro: float, cov: list[Coverage]) -> None:
    """All dashboard alerts in their original order. cov is the database coverage (db_queries.coverage), computed by the caller."""
    threshold_alerts(ctx, g, giro)
    for lvl, txt in data_gaps(rows, depot):
        ctx.add_alert(lvl, txt)
    for lvl, txt in gap_messages(cov):
        ctx.add_alert(lvl, txt)
    import_alerts(ctx, sync_rep)
    sonstiges_alert(ctx, flows)         # info level, so the "warnings first" order of dedupe_alerts is not affected
    dedupe_alerts(ctx)

"""The light refresh patches: fresh Coinbase balances, live prices on the depot and the gross / net wealth series."""
from __future__ import annotations
from ..common import safenet
from ..common.parsing import round2
from ..common.runcontext import RunContext, run_stage
from ..common.timeutil import now_month
from ..common.types.datajson import DataJson
from ..data.finance.positions import depot_totals, enrich_crypto_cost
from ..data.ingest import loaders
from .totals import gross_and_net


def quick_crypto(ctx: RunContext, data: DataJson) -> None:
    """Fresh Coinbase balances (keeping the stored price history) replace data["crypto"]."""
    cb = run_stage(ctx, "quick.quick_crypto", lambda: loaders.load_coinbase(ctx), None)       # Coinbase is optional: the quick refresh keeps the stored balances
    if cb and cb.get("holdings"):
        old = {h["currency"]: h for h in (data.get("crypto") or {}).get("holdings", [])}
        for h in cb["holdings"]:
            h["hist"] = (old.get(h["currency"]) or {}).get("hist")
        enrich_crypto_cost(cb)
        data["crypto"] = cb


def _last_point_is_current(data: DataJson) -> bool:
    """True when the last point of the monthly series belongs to the current month (a stored document without an axis is taken as current).
    After a month change the last point is last month's closing value: it must not be overwritten with today's live value (the full refresh adds the new month)."""
    axis = data.get("axis")
    if not axis:
        return True
    if axis[-1] == now_month():
        return True
    safenet.log.info("quick refresh: the stored series ends in %s, not the current month - last points left unchanged", axis[-1])
    return False


def quick_depot(data: DataJson, px: dict[str, float]) -> None:
    """Applies live prices to the depot positions, recomputes the depot totals and the last Securities point."""
    d = data.get("depot")
    if d:
        for p in d["positions"]:
            qty, cost = p["qty"], p["cost"]
            if p["wkn"] in px and qty:
                p["price_live"] = px[p["wkn"]]
                p["value"] = round2(qty * px[p["wkn"]])
                if cost:
                    p["gain"] = round2(p["value"] - cost)
                    p["gain_pct"] = round2((p["value"] / cost - 1) * 100)
        depot_totals(d)
        if data["nw"].get("Securities") and _last_point_is_current(data):
            data["nw"]["Securities"][-1] = round(sum(p["value"] for p in d["positions"]), 0)
    cb = data.get("crypto")
    if cb and data["nw"].get("Crypto") and _last_point_is_current(data):
        data["nw"]["Crypto"][-1] = round(cb["total_eur"], 0)


def quick_nwx(data: DataJson) -> None:
    """Refreshes the gross and net wealth series after the last points changed."""
    try:
        data["nwx"]["gross"], data["nwx"]["net"] = gross_and_net(data["nw"], data["nwx"]["loan"], len(data["nw"]["Cash"]))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        safenet.swallowed("quick.quick_nwx", exc)

"""Runs the analytics for data.json: fetches the optional outside data (benchmark, inflation, fund profiles) with a cache, then builds data["analytics"]."""
from __future__ import annotations
from typing import Any
import json, time
from pathlib import Path
from ..common import config, safenet
from ..common.fileio import load_json_cache, write_atomic
from ..common.paths import data_path
from ..common.profile import load_profile
from ..common.runcontext import RunContext, run_stage
from ..common.timeutil import DAY_S, HOUR_S, axis
from ..common.types.datajson import AnalyticsError, DataJson
from ..data.finance.models import no_tax_estimate
from ..data.ingest.quotes import MARKET_ERRORS, align, monthly_closes
from . import analytics, research

EXTERNAL_TTL_S, PROFILE_TTL_S = 20 * HOUR_S, 30 * DAY_S
HICP_URL = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_midx"
            "?format=JSON&lang=EN&geo=DE&coicop=CP00&unit=I15&sinceTimePeriod={since}")


def refresh_external(ctx: RunContext, data: DataJson, cache: dict[str, Any]) -> None:
    """MSCI-World proxy, German inflation index (daily) and Yahoo fund/stock profiles (monthly per WKN). Every source is
    optional: a failure only leaves that part of the analytics at n/a."""
    t_now = time.time()

    def benchmark() -> None:
        cache["bench"] = align(monthly_closes(config.cfg_value("index_benchmark.symbol"), "EUR"))
        cache["bench_t"] = t_now

    def inflation() -> None:
        cache["cpi"] = analytics.parse_hicp(safenet.fetch_json(HICP_URL.format(since=axis()[0]), 20), axis())
        cache["cpi_t"] = t_now

    profiles, times = cache.setdefault("profiles", {}), cache.setdefault("profiles_t", {})

    def fund_profiles() -> None:
        depot = data.get("depot")
        for p in (depot["positions"] if depot else []):
            wkn, sym = p["wkn"], p.get("sym")
            if sym and t_now - times.get(wkn, 0) >= PROFILE_TTL_S:
                pr = research.fund_profile(sym)
                if pr:
                    profiles[wkn], times[wkn] = pr, t_now

    # one timestamp per source: a source that failed is retried at the next refresh, one that worked waits EXTERNAL_TTL_S
    if t_now - cache.get("bench_t", 0) >= EXTERNAL_TTL_S:
        run_stage(ctx, "analytics_run.benchmark", benchmark, None, status="benchmark", errors=MARKET_ERRORS)
    if t_now - cache.get("cpi_t", 0) >= EXTERNAL_TTL_S:
        run_stage(ctx, "analytics_run.inflation", inflation, None, status="inflation", errors=MARKET_ERRORS)
    run_stage(ctx, "analytics_run.profiles", fund_profiles, None, status="profiles")


def compute_analytics(ctx: RunContext, data: DataJson, external: bool = False, cache_path: str | Path | None = None) -> None:
    """data["analytics"] = wealth-manager measures; never raises (a problem is reported inside the result)."""
    path = Path(cache_path) if cache_path else data_path("analytics_cache.json")
    cache = load_json_cache(path, {})
    try:
        if external:
            refresh_external(ctx, data, cache)
            run_stage(ctx, "analytics_run.cache_write", lambda: write_atomic(path, json.dumps(cache, ensure_ascii=False)), None,
                      errors=(OSError, ValueError, TypeError))       # a cache that cannot be saved only costs a refetch next time
        cfg = {k: config.cfg_value(k) for k in ("targets", "stress", "risk_free", "index_benchmark", "tax")}
        data["analytics"] = analytics.build_analytics(data, cache.get("bench"), cache.get("cpi"), cache.get("profiles"), cfg)
        if load_profile().tax_country != "DE":
            data["analytics"]["tax"] = no_tax_estimate()       # type: ignore[typeddict-unknown-key]
    except Exception as e:          # broad on purpose: analytics must not stop the refresh; the error is shown on the page
        safenet.swallowed("analytics_run.compute_analytics", e)
        data["analytics"] = AnalyticsError(error="%s: %s" % (type(e).__name__, str(e)))

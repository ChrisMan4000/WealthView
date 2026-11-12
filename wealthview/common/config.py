"""WealthView - config.json: the ONE module that reads it (re-read when the file changes), plus the built-in defaults and the dotted-path lookup.
Other modules ask for a single setting: setting("name", default), section("name"), cfg_value("a.b.c"), oneoff_threshold() or own_names();
only the app layer passes the whole config dict around (folder watcher, source reminders)."""
from __future__ import annotations
from typing import Any
import json
from pathlib import Path
from . import paths, safenet


class _ConfigCache:
    """config.json as last read, and the file's modification time at that moment"""
    value: dict[str, Any] | None = None
    mtime_ns: int | None = None


_CONFIG = _ConfigCache()


def load_config() -> dict[str, Any]:
    """config.json, cached. It is read again when the file's modification time changes (so a long-running server sees edits).
    Treat the result as read-only: change settings in the file, never in this dict."""
    f = paths.BASE / "config.json"
    try:
        mtime: int | None = f.stat().st_mtime_ns
    except OSError:
        mtime = None            # file not readable: keep what we have (reading it below raises if there is nothing yet)
    if _CONFIG.value is None or (mtime is not None and mtime != _CONFIG.mtime_ns):
        _CONFIG.value = json.loads(f.read_text("utf-8-sig"))
        _CONFIG.mtime_ns = mtime
    return _CONFIG.value


def setting(name: str, default: Any = None) -> Any:
    """One top-level setting of config.json, or `default` when it is not there."""
    return load_config().get(name, default)


def section(name: str) -> Any:
    """A top-level setting that must exist (KeyError when config.json lacks it)."""
    return load_config()[name]


def oneoff_threshold() -> float:
    """Bookings of this size (EUR) or more are shown as one-offs, not as run-rate (config.json -> oneoff_threshold_eur, default 3000)."""
    return setting("oneoff_threshold_eur", 3000)       # not converted: the value goes into data.json as written


def owner_display() -> str:
    """The owner's display name (config.json -> display_name), or "" when not set."""
    return str(load_config().get("display_name") or "").strip()


def own_names() -> list[str]:
    """Lower-case names of the account owners (config.json -> owner_names), used to recognise transfers between own accounts."""
    names = (n.strip().lower() for n in load_config().get("owner_names", []))
    return [n for n in names if n]      # an empty name would match every counterparty


# Defaults for the v1.06 analytics settings; config.json values win (see cfg_value)
DEFAULTS: dict[str, Any] = {
    "targets": {
        "Real estate":    {"target": 35, "low": 28, "high": 42},
        "Securities":     {"target": 40, "low": 33, "high": 47},
        "Private equity": {"target": 12, "low": 8,  "high": 15},
        "Crypto":         {"target": 5,  "low": 3,  "high": 8},
        "Cash":           {"target": 8,  "low": 5,  "high": 12},
    },
    "unusual": {"new_merchant_eur": 250, "dup_days": 5, "dup_min_eur": 10, "spike_mad": 3, "spike_min_eur": 50, "min_history": 4,
                "rise_pct": 5, "lookback_days": 180, "warmup_days": 90},
    "index_benchmark": {"symbol": "EUNL.DE", "name": "iShares Core MSCI World"},
    "risk_free": 0.02,
    "tax": {"rate_pct": 26.375, "allowance_eur": 1000, "grundfreibetrag_eur": 12348, "sonderausgaben_pauschbetrag_eur": 36,
            "other_income_eur": 0, "other_deductions_eur": 0, "filing": "single", "church_tax": False},
    "apartment_sale": {"own_use": True, "selling_cost_pct": 0.0, "acquisition_costs_eur": 0, "freigrenze_eur": 1000},
    "stress": {"Securities": -0.30, "Crypto": -0.60, "Real estate": -0.15, "Private equity": -0.30, "Cash": 0.0},
}


def cfg_value(path: str | Path, default: Any = None) -> Any:
    """Value for a dotted path (e.g. "targets.Crypto.high"): config.json first, then DEFAULTS, then `default`."""
    for root in (load_config(), DEFAULTS):
        cur: Any = root
        try:
            for part in str(path).split("."):
                cur = cur[part]
            return cur
        except (KeyError, TypeError) as exc:      # path missing in this candidate dict: try the next one
            safenet.swallowed("config.cfg_lookup", exc, routine=True)
    return default

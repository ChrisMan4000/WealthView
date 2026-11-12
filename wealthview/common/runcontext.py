"""WealthView - RunContext: the per-run collectors (source status, dashboard alerts, parse-cache hits) and run_stage()."""
from __future__ import annotations
from typing import Any, Callable, TypeVar
from dataclasses import dataclass, field
import threading
from . import safenet
from .types.status import Alert, Level, SourceStatus, State

UNCHANGED = " · unchanged since last read"
T = TypeVar("T")
_NOT_GIVEN: Any = object()      # marks "this extra field was not passed" (None is a real value for asof)


@dataclass
class RunContext:
    """Per-run collectors: source status, dashboard alerts and parse-cache hits.
    One instance is created by refresh.main()/quick_main() and passed to the stage functions. Writers go through
    set_status/add_alert/snapshot, which hold a lock, so another thread can read it safely."""
    status: dict[str, SourceStatus] = field(default_factory=dict)
    alerts: list[Alert] = field(default_factory=list)
    cache_hits: dict[str, bool] = field(default_factory=dict)      # parse-cache name -> True when the last cached_parse() used the cache
    _lock: Any = field(default_factory=threading.RLock, repr=False, compare=False)

    def set_status(self, name: str, state: State, msg: str = "", *, detail: list[str] = _NOT_GIVEN, asof: str | None = _NOT_GIVEN,
                   live: bool = _NOT_GIVEN) -> None:
        """Sets the status line of one source. detail / asof / live are stored only when given."""
        entry: SourceStatus = {"state": state, "msg": msg}
        if detail is not _NOT_GIVEN:
            entry["detail"] = detail
        if asof is not _NOT_GIVEN:
            entry["asof"] = asof
        if live is not _NOT_GIVEN:
            entry["live"] = live
        with self._lock:
            self.status[name] = entry

    def add_alert(self, level: Level, text: str) -> None:
        with self._lock:
            self.alerts.append({"level": level, "text": text})

    def snapshot(self) -> dict[str, SourceStatus]:
        """Copy of the per-source status: the dict and every entry are copied, so the caller may change them freely."""
        with self._lock:
            return {k: v.copy() for k, v in self.status.items()}


def run_stage(ctx: RunContext, label: str, fn: Callable[[], T], default: T, *, status: str | None = None, alert: bool = False,
              msg: str = "", errors: tuple[type[BaseException], ...] = (Exception,)) -> T:
    """Runs one optional stage. If `fn` raises one of `errors` the run goes on with `default`: the error is logged
    (safenet.swallowed) and, as asked, shown on the page: a warning status line for `status` and/or a warning alert (`alert=True`),
    each reading `msg` + the error text. Use it for steps that must never stop a refresh."""
    try:
        return fn()
    except errors as exc:       # broad on purpose (callers choose `errors`): an optional stage must not stop the refresh
        safenet.swallowed(label, exc)
        if status:
            ctx.set_status(status, "warn", msg + str(exc))
        if alert:
            ctx.add_alert("warn", msg + str(exc))
        return default


def unchanged_note(ctx: RunContext, cache_name: str) -> str:
    """' · unchanged since last read' when the parse cache named `cache_name` was used."""
    return UNCHANGED if ctx.cache_hits.get(cache_name) else ""


def db_unchanged_note(ctx: RunContext) -> str:
    """' · unchanged since last read' when the database sync was skipped (refresh_stages.open_db marks its status text with UNCHANGED)."""
    database = ctx.snapshot().get("database")
    return UNCHANGED if database and database["msg"].endswith(UNCHANGED) else ""

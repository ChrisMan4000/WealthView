"""WealthView - security audit trail: one line per sensitive event (unlock, lock-out, refresh, question) in audit.log.
Only the event name, the time and a short non-secret detail are written - never a PIN, token or the text of a question."""
from __future__ import annotations
import threading, time
from pathlib import Path

from . import paths
from . import timeutil
from . import fileio
from . import safenet

MAX_BYTES = 256 * 1024              # above this the older half is dropped, so the log never grows without bound
_LOCK = threading.Lock()
COLLAPSE_S = 60                     # repeated lock-out refusals: the first is logged, then one summary line per this many seconds
_COLLAPSED = frozenset({"unlock_refused_lockout"})
_seen: dict[tuple[str, str], tuple[float, int]] = {}      # (log file, event) -> (time of the last written line, refusals held back since)


def record(event: str, detail: str = "", path: Path | None = None) -> None:
    """Append '<local time> <event> <detail>' to the audit log; a failure to write must never break the request."""
    target = Path(path) if path else paths.data_path("audit.log")
    if event in _COLLAPSED:
        with _LOCK:
            key, t = (str(target), event), time.monotonic()
            last, held = _seen.get(key, (None, 0))
            if last is not None and t - last < COLLAPSE_S:
                _seen[key] = (last, held + 1)
                return
            _seen[key] = (t, 0)
        if held:
            detail = f"{held} more in the last minute" + (f" ({detail})" if detail else "")
    line = f"{timeutil.now().isoformat(timespec='seconds')} {event} {detail}".rstrip() + "\n"
    with _LOCK:
        try:
            old = target.read_text("utf-8") if target.exists() else ""
            if len(old) > MAX_BYTES:
                old = old[len(old) // 2:].split("\n", 1)[-1]
            fileio.write_atomic(target, old + line)
        except (OSError, ValueError, TypeError) as exc:
            safenet.swallowed("audit.record", exc)

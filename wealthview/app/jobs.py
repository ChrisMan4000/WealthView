"""WealthView server background jobs: the refresh subprocess (one at a time) and the folder watcher."""
from __future__ import annotations
from typing import Any, Callable
import os, subprocess, sys, threading, time  # nosec B404 - only runs this program's own refresh.py
from ..common import config, paths, safenet
from ..data.ingest import db_import, db_schema

QUICK_REFRESH_TIMEOUT_S = 120
FULL_REFRESH_TIMEOUT_S = 240
WATCH_BACKOFF_S = 600       # longest extra wait of the folder watcher (after a failed refresh, or a refresh that did not settle the folders)
WATCH_STEP_S = 60           # first extra wait when the folders still look "changed" right after a good refresh; doubles each time


def user_env(name: str) -> str | None:
    """An environment variable; on Windows also the user's own variables from the registry (a GUI start does not see them)."""
    v = os.environ.get(name)
    if v:
        return v
    if sys.platform != "win32":      # the registry only exists on Windows (this also keeps mypy from checking winreg on other systems)
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:     # the variable is not set
        return None


class Refresher:
    """Runs refresh.py (full or --quick) in a subprocess; only one at a time."""

    def __init__(self, on_finished: Callable[[], None] | None = None) -> None:
        self.lock = threading.Lock()
        self.on_finished = on_finished      # called after the subprocess ended (the server drops its live-quote cache there)

    def run(self, args: list[str] | None = None, tmo: int = FULL_REFRESH_TIMEOUT_S) -> dict[str, Any]:
        """Starts the refresh and waits for it -> {ok, seconds, log, error?}; {ok: False, busy: True} when one is already running."""
        if not self.lock.acquire(blocking=False):
            return dict(ok=False, busy=True, error="a refresh is already running", log="a refresh is already running")
        try:
            env = dict(os.environ)
            for n in ("COINBASE_KEY_NAME", "COINBASE_KEY_SECRET"):
                v = user_env(n)
                if v:
                    env[n] = v
            env["PYTHONIOENCODING"] = "utf-8"
            t0 = time.time()
            try:
                p = subprocess.run([sys.executable.replace("pythonw.exe", "python.exe"), str(paths.BASE / "refresh.py")] + (args or []),  # nosec B603 - fixed argument list, no shell
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=tmo,
                                   cwd=str(paths.BASE), env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if self.on_finished:
                    self.on_finished()
                ok = p.returncode == 0
                return dict(ok=ok, seconds=round(time.time() - t0, 1), log=(p.stdout or p.stderr or "")[-600:], **({} if ok else {"error": "refresh failed"}))
            except (OSError, subprocess.SubprocessError) as e:     # could not start / timed out
                return dict(ok=False, error=str(e), log=str(e))
        finally:
            self.lock.release()


def extra_wait_after(result: dict[str, Any], stuck: int = 0) -> int:
    """Seconds the folder watcher waits on top of its normal pause.
    * another refresh was already running (busy) -> 0, that is not a failure
    * the refresh failed (e.g. no network) -> WATCH_BACKOFF_S
    * the refresh was fine but the folders still look changed afterwards (e.g. an unreadable file), `stuck` times in a row
      -> 60 s, 120 s, 240 s ... never more than WATCH_BACKOFF_S, so the watcher cannot refresh over and over
    * otherwise 0."""
    if result.get("busy"):
        return 0
    if not result.get("ok"):
        return WATCH_BACKOFF_S
    return min(WATCH_BACKOFF_S, WATCH_STEP_S * 2 ** (stuck - 1)) if stuck > 0 else 0


def folders_changed() -> bool:
    """True when the watched GLS / PayPal folders have new or changed files, or data.json does not exist yet."""
    conn = db_schema.connect(paths.data_path(db_schema.DB_NAME))
    try:
        return db_import.folders_changed(conn, config.load_config()) or not paths.data_path("data.json").exists()
    finally:
        conn.close()


def folder_watcher(refresher: Refresher, every: int = 60) -> None:
    """New downloads in the GLS / PayPal folders -> a full refresh (which imports them into the database) without anyone pressing a button.
    Checks a cheap signature (file names, sizes, times) once a minute; the page picks the new data up with its next quick update."""
    time.sleep(5)
    stuck = 0       # refreshes in a row after which the folders still looked changed
    while True:
        try:
            if folders_changed():
                safenet.log.info("new or changed files in the watched folders - refreshing")
                result = refresher.run()
                stuck = stuck + 1 if result.get("ok") and folders_changed() else 0
                time.sleep(extra_wait_after(result, stuck))
            else:
                stuck = 0
        except Exception as e:      # broad on purpose: background watcher must keep running
            safenet.log.warning("folder watcher: %s", e)
        time.sleep(every)

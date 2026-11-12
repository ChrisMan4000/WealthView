"""WealthView server lifetime: it runs only while a browser tab is open.

The page sends a heartbeat every 10 s (/api/hb) and a goodbye when it is closed (/api/bye). The server ends itself when no page
is left (grace 12 s after a goodbye so that a reload does not stop it, 60 s without heartbeats after a crash, 5 min if no page
ever connects). A sleeping PC does not count as "gone". config.json "auto_stop": false keeps the server running always.
"""
from __future__ import annotations
import os, threading, time
from ..common import safenet

HB_TIMEOUT, BYE_GRACE, FIRST_GRACE = 60, 12, 300
MAX_CLIENTS = 50          # most browser pages the heartbeat table remembers (/api/hb is public, so it must not grow without limit)
SLEEP_GAP_S = 30          # a pause between two watchdog checks longer than this means the PC was asleep


def should_stop(now: float, has_clients: bool, seen: bool, empty_since: float | None, started: float) -> tuple[bool, float | None]:
    """The watchdog's decision as a pure function -> (stop the server?, new `empty_since`).
    * a page is open: never stop
    * no page ever connected: stop FIRST_GRACE seconds after the start
    * the last page went away: stop HB_TIMEOUT seconds after that moment"""
    if has_clients:
        return False, empty_since
    if not seen:
        return now - started > FIRST_GRACE, empty_since
    if empty_since is None:
        empty_since = now
    return now - empty_since >= HB_TIMEOUT, empty_since


class PageLife:
    """Open browser pages (client id -> last heartbeat) and the server's lifetime bookkeeping."""

    def __init__(self) -> None:
        self.clients: dict[str, float] = {}
        self.seen = False
        self.empty_since: float | None = None
        self.started = time.time()
        self.lock = threading.Lock()

    def heartbeat(self, cid: str) -> None:
        """A page is alive."""
        with self.lock:
            now = time.time()
            if cid not in self.clients and len(self.clients) >= MAX_CLIENTS:
                for k in [k for k, v in self.clients.items() if now - v > HB_TIMEOUT]:
                    self.clients.pop(k, None)               # first drop pages that stopped sending heartbeats
                if len(self.clients) >= MAX_CLIENTS:
                    self.clients.pop(min(self.clients, key=lambda k: self.clients[k]))      # still full: the oldest one makes room
            self.clients[cid] = now
            self.seen = True
            self.empty_since = None

    def goodbye(self, cid: str) -> None:
        """A page was closed."""
        with self.lock:
            self.clients.pop(cid, None)
            if not self.clients:
                self.empty_since = time.time() - (HB_TIMEOUT - BYE_GRACE)    # leaves BYE_GRACE seconds for a reload

    def should_stop_now(self, now: float, last_check: float) -> bool:
        """One watchdog check: forgets pages without a heartbeat and decides whether the server should stop."""
        with self.lock:
            if now - last_check > SLEEP_GAP_S:        # the PC was asleep: nobody could send heartbeats, so do not count it
                for k in self.clients:
                    self.clients[k] = now
            for k in [k for k, v in self.clients.items() if now - v > HB_TIMEOUT]:
                self.clients.pop(k, None)
            gone, self.empty_since = should_stop(now, bool(self.clients), self.seen, self.empty_since, self.started)
        return gone


def watchdog(life: PageLife) -> None:
    """Checks every 3 seconds; ends the program when no browser page is left."""
    last = time.time()
    while True:
        time.sleep(3)
        now = time.time()
        gone = life.should_stop_now(now, last)
        last = now
        if gone:
            safenet.log.info("no browser page left - server stops")
            os._exit(0)

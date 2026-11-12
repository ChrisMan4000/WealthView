"""WealthView source plugins, part 1: the SourcePlugin interface, the registry and detect_best().
A plugin recognises a file by its first bytes (detect) and reads it (parse). detect() never opens files; detect_best() is the only place that does.
Layering: plugins live in data/ingest and import only from common and sibling ingest modules (never db_import)."""
from __future__ import annotations
from typing import Any, Protocol

HEAD_BYTES = 4096          # how much of a file detect_best() reads and hands to detect()
MIN_CONFIDENCE = 0.5       # detect_best() returns None when even the best plugin is less sure than this


class SourcePlugin(Protocol):
    """name: registry key. detect(path, head): confidence 0..1 that the file is this source, from the file name and its first bytes only (no IO).
    parse(path): the file's records. Bank bookings are BookingRow dicts; a source whose file is not a list of bookings (depot export, PayPal activity
    rows, Coinbase holdings) returns its own record dicts."""
    name: str

    def detect(self, path: str, head: bytes) -> float: ...

    def parse(self, path: str) -> list[Any]: ...


REGISTRY: dict[str, SourcePlugin] = {}


def register(plugin: SourcePlugin) -> SourcePlugin:
    """Add a plugin under its name (a later registration of the same name replaces the earlier one)."""
    REGISTRY[plugin.name] = plugin
    return plugin


def head_text(head: bytes) -> str:
    """Printable text of a file head for detect(): '' for binary/empty heads; BOM stripped; a multi-byte character cut by the head limit is tolerated."""
    if not head or b"\x00" in head:
        return ""
    return head.decode("utf-8-sig", errors="replace") if head[:3] == b"\xef\xbb\xbf" or _is_utf8(head) else head.decode("cp1252", errors="replace")


def _is_utf8(head: bytes) -> bool:
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        return exc.start >= len(head) - 3 and exc.reason == "unexpected end of data"       # only the last character is cut


def detect_best(path: str) -> tuple[str, float] | None:
    """(plugin name, confidence) of the most confident plugin for the file, or None when it is unreadable or below MIN_CONFIDENCE.
    Reads at most HEAD_BYTES in binary mode and never writes. Ties go to the plugin registered first."""
    try:
        with open(path, "rb") as f:
            head = f.read(HEAD_BYTES)
    except OSError:
        return None
    best: tuple[str, float] | None = None
    for name, plugin in list(REGISTRY.items()):
        try:
            conf = float(plugin.detect(path, head))
        except Exception:      # a broken plugin must not stop the scan: it just does not recognise the file
            continue
        if conf >= MIN_CONFIDENCE and (best is None or conf > best[1]):
            best = (name, min(conf, 1.0))
    return best

"""WealthView - the parse cache: a source file is parsed again only when it is new or changed (size / modification time)."""
from __future__ import annotations
from typing import Any, Callable, TypeVar, cast
from collections.abc import Sequence
import json, os
from pathlib import Path
from . import safenet
from .fileio import load_json_cache, write_atomic
from .paths import data_path
from .runcontext import RunContext

R = TypeVar("R")      # whatever a parse function returns


def file_signature(paths: Sequence[str | Path]) -> list[list[str | int | None]]:
    """[[path, size, mtime_ns]] of the input files, sorted by path; a file that cannot be stat'ed gets [path, None, None]."""
    sig: list[list[str | int | None]] = []
    for p in sorted(str(x) for x in paths):
        try:
            st = os.stat(p)
            sig.append([p, st.st_size, st.st_mtime_ns])
        except OSError:
            sig.append([p, None, None])
    return sig


def cached_parse(ctx: RunContext, name: str, paths: list[Path], parse: Callable[[list[Path]], R], cache_file: str | Path | None = None) -> R:
    """parse(paths) for the input files, but only when they are new or changed: the result (must be JSON-serialisable)
    is stored in parse_cache.json under `name`, keyed by (path, size, mtime_ns) of every file. A missing or corrupt cache
    simply means "parse normally"; a cache that cannot be written is ignored. ctx.cache_hits[name] tells whether the cache was used.
    A cache hit returns the stored JSON value, which has the shape `parse` returned (JSON turns tuples into lists)."""
    cf = Path(cache_file) if cache_file else data_path("parse_cache.json")
    sig = file_signature(paths)
    cache: dict[str, Any] = load_json_cache(cf, {})
    ent = cache.get(name)
    if isinstance(ent, dict) and ent.get("sig") == sig and "data" in ent:
        ctx.cache_hits[name] = True
        return cast(R, ent["data"])
    ctx.cache_hits[name] = False
    result = parse(list(paths))
    try:
        cache[name] = dict(sig=sig, data=result)
        write_atomic(cf, json.dumps(cache, ensure_ascii=False, separators=(",", ":")))
    except (OSError, TypeError, ValueError) as exc:
        safenet.swallowed("parse_cache.cached_parse", exc)
    return result

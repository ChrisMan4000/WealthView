"""WealthView - file helpers: atomic writes (temp file, then os.replace, so a crash never leaves a half-written file) and the JSON cache reader."""
from __future__ import annotations
import json
import os
import threading
from pathlib import Path
from typing import Any

from . import safenet


def write_atomic(path: Path | str, data: str | bytes, encoding: str = "utf-8") -> None:
    """Write `data` (text or bytes) to `path` via a temp file in the same folder plus os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)      # the data folder does not exist before the first start
    # unique per process and thread: two request threads writing the same cache file must not share one temp file
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        if isinstance(data, bytes):
            tmp.write_bytes(data)
        else:
            tmp.write_text(data, encoding)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)       # never leave a half-written temp file behind
        raise


def load_json_cache(path: Path | str, default: Any) -> Any:
    """The one JSON cache loader: the parsed file, or `default` when the file is missing, unreadable, not valid JSON or not
    the same kind of value as `default` (a dict cache never turns into a list). Never raises - a cache is only a shortcut."""
    try:
        data = json.loads(Path(path).read_text("utf-8-sig"))
    except OSError:
        return default
    except ValueError as exc:
        safenet.swallowed("fileio.load_json_cache", exc)
        return default
    return data if default is None or isinstance(data, type(default)) else default

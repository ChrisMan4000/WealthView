"""WealthView v1.21: where API keys typed in under Setup are kept. One entry per place in the Windows Credential Manager (target
"WealthView-API-<id of the place>"), protected by the user's Windows sign-in. Keys never go into config.json, the database, a log, data.json or back to
the browser: the setup screen only learns whether a place has keys. Standard library only."""
from __future__ import annotations
import json, sys

from . import credstore

PREFIX = "WealthView-API-"
MAX_BLOB = 2560                      # bytes Windows accepts for one credential
_memory: dict[str, str] | None = None      # tests set this to a dict: the keys then stay in memory and Windows is not touched


def _target(source_id: int) -> str:
    return f"{PREFIX}{int(source_id)}"


def available() -> bool:
    """True when keys can be stored on this computer."""
    return _memory is not None or sys.platform == "win32"


def save(source_id: int, values: dict[str, str]) -> None:
    """Stores the keys of one place (replacing older ones). ValueError with a plain sentence when that is not possible."""
    blob = json.dumps({str(k): str(v) for k, v in values.items()}, ensure_ascii=False)
    if len(blob.encode("utf-16-le")) > MAX_BLOB:
        raise ValueError("these keys are too long to be stored")
    if _memory is not None:
        _memory[_target(source_id)] = blob
        return
    if sys.platform != "win32":
        raise ValueError("API keys can only be stored on Windows (Credential Manager)")
    if not credstore.cred_write(blob, user="api", target=_target(source_id)):
        raise ValueError("Windows could not store the keys (Credential Manager)")


def load(source_id: int) -> dict[str, str]:
    """The stored keys of one place; {} when there are none."""
    blob = _memory.get(_target(source_id)) if _memory is not None else credstore.cred_read(_target(source_id))
    if not blob:
        return {}
    try:
        got = json.loads(blob)
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in got.items()} if isinstance(got, dict) else {}


def has(source_id: int) -> bool:
    return bool(load(source_id))


def delete(source_id: int) -> None:
    """Removes the keys of one place (nothing happens when there are none)."""
    if _memory is not None:
        _memory.pop(_target(source_id), None)
        return
    if sys.platform != "win32":
        return
    credstore.cred_delete(_target(source_id))

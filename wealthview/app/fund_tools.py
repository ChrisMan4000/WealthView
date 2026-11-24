"""The two helpers the refresh hands to the typed-asset numbers (v1.23): a fund report reader that can ask the local LM Studio model about layouts it
does not know, and the price lookup by ISIN. The report answers are remembered per file (data/fund_reports_cache.json), so the model is asked once."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable

from ..analysis import ask
from ..common import config
from ..common.fileio import write_atomic
from ..common.paths import data_path
from ..data.ingest import fund_files

CACHE_NAME = "fund_reports_cache.json"


def make_asker(cfg: dict[str, Any] | None = None) -> Callable[[str, str], str]:
    """ask(system, user) -> reply from the LM Studio on this computer. The model is looked up on first use; RuntimeError when none is loaded."""
    cfg = cfg if cfg is not None else config.load_config().get("ask", {})
    base = cfg.get("url", ask.LM_DEFAULT_URL)
    state: dict[str, str] = {}

    def _ask(system: str, user: str) -> str:
        if "model" not in state:
            state["model"] = ask.pick_model(base, cfg.get("model", "auto"), cfg.get("model_match"))
        return ask.lm_chat(base, state["model"], [{"role": "system", "content": system}, {"role": "user", "content": user}],
                           int(cfg.get("timeout_s", ask.DEFAULT_TIMEOUT_S)))
    return _ask


def _load(path: Path) -> dict[str, Any]:
    try:
        j = json.loads(path.read_text(encoding="utf-8"))
        return j if isinstance(j, dict) else {}
    except (OSError, ValueError):
        return {}


def make_fund_reader(asker: Callable[[str, str], str] | None = None, cache_path: Path | None = None) -> Callable[[str, float | None], dict[str, Any]]:
    """reader(folder, invested) -> what fund_files.read_folder finds, with the per-file memory kept on disk."""
    path = cache_path or data_path(CACHE_NAME)
    ask_fn = asker or make_asker()

    def reader(folder: str, invested: float | None) -> dict[str, Any]:
        cache = _load(path)
        before = json.dumps(cache, sort_keys=True)
        res = fund_files.read_folder(folder, ask_fn, invested, cache)
        if json.dumps(cache, sort_keys=True) != before:
            try:
                write_atomic(path, json.dumps(cache))
            except OSError:
                pass                       # the memory is only a speed-up
        return res
    return reader


"""WealthView - where things live: the program folder (BASE), the data folder and the one-time move of old data files."""
from __future__ import annotations
import os, re, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent      # the folder with config.json and the web files (one above the wealthview package)
DATA_DIR = BASE / "data"                           # everything the program writes: database, data.json, caches, logs


def data_path(name: str) -> Path:
    """Path of a runtime file (database, data.json, cache, log) inside the data folder."""
    return DATA_DIR / name


def version() -> str:
    """The version number from version.js (the one place it lives); "v?" when the file is missing or unreadable."""
    try:
        m = re.search(r"WV_VERSION\s*=\s*'([^']+)'", (BASE / "version.js").read_text("utf-8"))
    except OSError:
        return "v?"
    return m.group(1) if m else "v?"


# files that used to sit in the main folder before v1.14 (moved into data/ by migrate_data_dir)
_LEGACY_DATA_FILES = ("wealthview.db", "wealthview.db-journal", "wealthview.db-wal", "wealthview.db-shm", "data.json", "history.json",
                      "parse_cache.json", "analytics_cache.json", "coinbase_cache.json", "company_cache.json", "logos_online.json",
                      "netgeo.json", "netlog.jsonl", "audit.log", "refresh_error.log", "sonstiges_report.txt", "symbols.json")


def migrate_data_dir(base: Path | None = None) -> list[str]:
    """One-time move of the pre-v1.14 data files into data/. The originals are kept in _pre_data_dir_backup/ (never deleted).
    Files already present in data/ win. Returns the names that were moved."""
    root = base or BASE
    data, backup = root / "data", root / "_pre_data_dir_backup"
    moved: list[str] = []
    data.mkdir(exist_ok=True)
    for name in _LEGACY_DATA_FILES:
        old = root / name
        if not old.is_file():
            continue
        data.mkdir(exist_ok=True)
        backup.mkdir(exist_ok=True)
        if not (data / name).exists():
            shutil.copy2(old, data / name)
        os.replace(old, backup / name)
        moved.append(name)
    return moved

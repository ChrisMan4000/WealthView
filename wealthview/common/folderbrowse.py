"""The folder picker of the setup screen (v1.20): the sub-folders of a folder on this computer, so a person can click to a folder instead of typing a path.
Only folder names and the number of .csv files are returned, never file contents. Standard library only."""
from __future__ import annotations
import os
import string
from pathlib import Path
from typing import Any

MAX_DIRS = 300


def _start_places() -> list[Path]:
    home = Path.home()
    places = [p for p in (home, home / "Documents", home / "Desktop", home / "Downloads") if p.is_dir()]
    if os.name == "nt":
        places += [Path(f"{c}:\\") for c in string.ascii_uppercase if Path(f"{c}:\\").exists()]
    return places


def browse(path: str) -> dict[str, Any]:
    """{path, parent, dirs: [{name, path}], csv_files}. An empty path gives the start places (home, Documents, Desktop, Downloads, the drives)."""
    p = (path or "").strip().strip('"')
    if not p:
        return dict(path="", parent=None, dirs=[dict(name=str(d) if d.parent == d else d.name or str(d), path=str(d)) for d in _start_places()], csv_files=0)
    d = Path(p)
    if not d.is_dir():
        raise ValueError("this folder does not exist on this computer")
    dirs: list[dict[str, str]] = []
    csv = 0
    try:
        for e in sorted(d.iterdir(), key=lambda x: x.name.lower()):
            if e.is_dir() and not e.is_symlink() and not e.name.startswith("."):
                if len(dirs) < MAX_DIRS:
                    dirs.append(dict(name=e.name, path=str(e)))
            elif e.is_file() and e.name.lower().endswith(".csv"):
                csv += 1
    except OSError as exc:
        raise ValueError("this folder cannot be opened: " + exc.strerror if exc.strerror else "this folder cannot be opened") from None
    parent = str(d.parent) if d.parent != d else None
    return dict(path=str(d), parent=parent, dirs=dirs, csv_files=csv)

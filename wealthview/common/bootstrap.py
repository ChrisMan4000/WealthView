"""WealthView - the one start-up routine of every program (server.py and refresh.py call bootstrap() first)."""
from __future__ import annotations
from . import config, netlog, paths, safenet


def bootstrap() -> list[str]:
    """Start-up steps, always in this order: set up logging (debug detail when "debug": true in config.json), move old files into data/
    (paths.migrate_data_dir), start the connection log (netlog; optional, a failure never stops the program).
    Safe to call more than once. Returns the names of the files that were moved into data/."""
    safenet.configure_logging(bool(config.load_config().get("debug", False)))
    moved = paths.migrate_data_dir()
    if moved:
        safenet.log.warning("moved %d data files into data/ (originals kept in _pre_data_dir_backup/)", len(moved))
    try:
        netlog.install()
    except Exception as exc:    # broad on purpose: optional diagnostics must never stop the program from starting
        safenet.swallowed("bootstrap.netlog", exc)
    return moved

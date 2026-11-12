"""Run health: source status, dashboard alerts and the database sync report."""
from __future__ import annotations
from typing import Literal, TypedDict


State = Literal["ok", "warn", "off"]                    # health of one data source


Level = Literal["info", "warn"]                         # severity of a dashboard alert


class Alert(TypedDict):
    """one dashboard alert (RunContext.add_alert)"""
    level: Level
    text: str


class _SourceStatusRequired(TypedDict):
    state: State
    msg: str


class SourceStatus(_SourceStatusRequired, total=False):
    detail: list[str]
    asof: str | None
    live: bool
    n_live: int | None
    n_total: int | None
    model: bool


class ImportedFile(TypedDict):
    """one newly imported file in a SyncReport"""
    name: str
    source: str
    rows: int
    new: int


class _SyncReportRequired(TypedDict):
    """what db_import.sync() returns (also stored as JSON in the meta table)"""
    at: str
    seen: int
    unchanged: int
    new_files: list[ImportedFile]
    duplicate_files: list[str]
    errors: list[str]
    new_bookings: int      # GLS bookings plus generic-CSV bookings (new_files[].source is "gls" or "csv")
    new_paypal: int
    new_depot: int


class SyncReport(_SyncReportRequired, total=False):
    skipped: bool      # refresh_stages.open_db sets it when the folders had not changed and no sync ran

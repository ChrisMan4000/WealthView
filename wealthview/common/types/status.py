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


class _ImportedFileRequired(TypedDict):
    name: str
    source: str
    rows: int
    new: int


class ImportedFile(_ImportedFileRequired, total=False):
    """one newly imported file in a SyncReport; source = the import kind (gls / depot / paypal / csv, or bank / card / depot / trades / crypto from the automatic reader), source_name = the user's name of the
    source the file belongs to (v1.19; absent while a database has no sources)"""
    source_name: str


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
    new_crypto: int    # crypto transactions read by the automatic reader (v1.20)
    questions: int     # files waiting for a plain answer after this sync (v1.20)

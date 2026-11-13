"""TypedDicts for sources (what the user set up) and accounts (what is found inside a source), v1.19."""
from __future__ import annotations
from typing import Any, TypedDict


class SourceRow(TypedDict):
    """One thing the user named in setup: a bank, an investment or a crypto place, with the folder / API it is read from."""
    id: int
    name: str
    section: str
    source_type: str
    folder: str | None
    connector: str | None
    reader: str
    options: dict[str, Any]
    active: bool
    legacy_key: str | None


class AccountRow(TypedDict):
    """One account inside a source (current account, card, depot, wallet ...). ident = IBAN or another stable id ('-' when unknown)."""
    id: int
    source_id: int
    name: str
    kind: str
    ident: str | None
    currency: str
    active: bool


class UpgradeReport(TypedDict):
    """Result of db_migrate.upgrade(): ok False = nothing changed (error says why); skipped = the database was already upgraded."""
    ok: bool
    skipped: bool
    sources: int
    accounts: int
    bookings_linked: int
    error: str | None

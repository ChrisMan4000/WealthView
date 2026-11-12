"""Typed records of the network log (netlog.py)."""
from __future__ import annotations
from typing import Any, TypedDict


class _GeoHitRequired(TypedDict):
    city: str
    country: str
    lat: float
    lon: float
    src: str


class GeoHit(_GeoHitRequired, total=False):
    """where a host is: the answer of netlog's IP lookups (database, web service, table); locate() adds ip and t (unix time)"""
    ip: str | None
    t: int


class NetlogSnapshot(TypedDict):
    """what netlog.snapshot() returns for the connection map"""
    sig: str
    home: dict[str, Any]
    nodes: list[dict[str, Any]]
    total: int
    hosts: int
    countries: int
    since: float | None
    now: float

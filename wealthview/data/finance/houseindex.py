"""Local house value development in Germany (v1.23): the Deutsche Bundesbank's residential property price indices by kind of area.

The Bundesbank publishes (free, no key) yearly price indices for owner-occupied flats and houses: the 7 largest cities, 127 cities, all German
districts (towns and rural districts) and the Destatis house price index for Germany. WealthView asks for the one series that fits the property
and nothing else - no address, no price, no name is sent. Immowelt and ImmoScout have no public interface and forbid automated reading, so
they are not used. The person can always type their own price per square metre, which then overrides the index.

Pure parts (parse_csv, annual_to_quarters) take plain values; fetch is the one web call and any failure just means "no index"."""
from __future__ import annotations
import csv
import io
import re
from typing import Any, Callable

from ...common import safenet

URL = "https://api.statistiken.bundesbank.de/rest/data/BBDY1/{key}"
ACCEPT = {"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"}
# area code -> (Bundesbank series key, plain-language label)
AREAS: dict[str, tuple[str, str]] = {
    "big7": ("A.B10.N.G100.P0030.A", "7 largest cities"),
    "city": ("A.B10.N.G100.P0010.A", "other cities (127-city index)"),
    "district": ("A.B10.N.G100.P0020.A", "towns and rural districts"),
    "germany": ("A.B10.N.G100.P0050.A", "Germany average (Destatis)"),
}
DEFAULT_AREA = "city"


def area_or_default(area: Any) -> str:
    a = str(area or "").strip().lower()
    return a if a in AREAS else DEFAULT_AREA


def label(area: Any) -> str:
    return AREAS[area_or_default(area)][1]


def parse_csv(text: str) -> dict[int, float]:
    """{2024: 242.3, ...} out of the Bundesbank CSV answer (semicolon separated, columns TIME_PERIOD and OBS_VALUE); empty for anything else."""
    try:
        rows = list(csv.reader(io.StringIO((text or "").lstrip("﻿")), delimiter=";"))
        head = rows[0]
        t, v = head.index("TIME_PERIOD"), head.index("OBS_VALUE")
    except (ValueError, IndexError):
        return {}
    out: dict[int, float] = {}
    for r in rows[1:]:
        if len(r) <= max(t, v) or not re.fullmatch(r"\d{4}", r[t].strip()):
            continue
        try:
            x = float(r[v].replace(",", "."))
        except ValueError:
            continue
        if x > 0:
            out[int(r[t])] = x
    return out


def annual_to_quarters(ann: dict[int, float]) -> dict[str, float]:
    """A yearly index as the quarterly dict the property model uses: each year counts for its middle (end of Q2), the quarters between two years
    move in a straight line, before the first year and after the last one the line stays flat."""
    if not ann:
        return {}
    years = sorted(ann)
    out: dict[str, float] = {}
    for y in range(years[0], years[-1] + 1):
        for q in range(1, 5):
            pos = y + (q - 2) / 4.0                      # Q2 -> y exactly
            lo = max([k for k in years if k <= pos] or [years[0]])
            hi = min([k for k in years if k >= pos] or [years[-1]])
            f = 0.0 if hi == lo else (pos - lo) / (hi - lo)
            out[f"{y}-Q{q}"] = round(ann[lo] + (ann[hi] - ann[lo]) * f, 4)
    return out


def fetch(area: Any = None, get_text: Callable[..., str] | None = None) -> dict[str, float] | None:
    """The quarterly index of an area type (None when the service is down or the answer is empty)."""
    key = AREAS[area_or_default(area)][0]
    get = get_text or safenet.fetch_text
    try:
        idx = annual_to_quarters(parse_csv(get(URL.format(key=key), headers=ACCEPT)))
    except safenet.NET_ERRORS as e:
        safenet.swallowed("Bundesbank house price index", e)
        return None
    return idx or None

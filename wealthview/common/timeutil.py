"""Date and time helpers shared by the whole program (kept dependency-free so the pure modules can import it)."""
from __future__ import annotations
import datetime as dt
from functools import lru_cache

HOUR_S = 3600
DAY_S = 86400


def month_key(d: dt.date) -> str:
    """'YYYY-MM' of a date or datetime."""
    return f"{d.year}-{d.month:02d}"


def month_list(n: int, end: dt.date) -> list[str]:
    """The last n 'YYYY-MM' keys up to and including the month of `end`, oldest first."""
    y, m = end.year, end.month
    out: list[str] = []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def mrange(a: str, b: str) -> list[str]:
    """All 'YYYY-MM' keys from a to b inclusive."""
    y, m = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    out: list[str] = []
    while (y, m) <= (yb, mb):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def now() -> dt.datetime:
    """The current local time (with time zone)."""
    return dt.datetime.now().astimezone()


def today() -> dt.date:
    """The current local day."""
    return now().date()


def now_month() -> str:
    """'YYYY-MM' of the current month."""
    return month_key(today())


NO_DATE = dt.date(1970, 1, 1)     # "no date": what the file-name date helpers return when a name has none or an impossible one


def safe_date(y: int | str, m: int | str, d: int | str) -> dt.date:
    """dt.date(y, m, d), or NO_DATE (1970-01-01) when the numbers are not a real calendar day (e.g. 31 February or month 13)."""
    try:
        return dt.date(int(y), int(m), int(d))
    except (ValueError, OverflowError):
        return NO_DATE


START_MONTH = "2020-11"  # apartment purchase = start of the long-term axis


@lru_cache(maxsize=1)
def axis() -> list[str]:
    """The shared month axis START_MONTH .. current month, computed on first use (not when the module is imported)."""
    return mrange(START_MONTH, now_month())

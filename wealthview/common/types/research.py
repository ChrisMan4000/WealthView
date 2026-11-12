"""Typed results of the research pop-up (metrics, analysts, news, scores) and of the Ask bar."""
from __future__ import annotations
from typing import Any, TypedDict


class QueryResult(TypedDict):
    """what ask.run_query() returns: column names, the rows (lists of cell values) and whether the row cap cut it off"""
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


class ChatMessage(TypedDict):
    role: str          # "system" | "user" | "assistant"
    content: str


class AskResult(TypedDict, total=False):
    """what ask.answer() returns; ok is always set, the other keys depend on success or failure"""
    ok: bool
    answer: str
    queries: list[dict[str, Any]]
    searches: list[dict[str, Any]]
    sources: list[dict[str, str]]
    model: str | None
    error: str
    detail: str


class Metrics(TypedDict):
    """price statistics of one security (research.metrics); percentages are in %, a missing value is None"""
    last: float
    sma50: float | None        # 50-day average
    sma200: float | None       # 200-day average
    r1m: float | None          # return over 1 / 6 / 12 months
    r6m: float | None
    r12m: float | None
    rsi: float | None          # relative strength index (14 days)
    hi52: float                # 52-week high / low
    lo52: float
    from_hi: float             # distance to the 52-week high
    vol: float | None          # yearly volatility


class Analyst(TypedDict, total=False):
    """analyst consensus from Yahoo Finance (research.analyst)"""
    rec_mean: float | None     # 1 = strong buy ... 5 = sell
    rec_key: str | None
    n: int | None              # number of analysts
    target: float | None       # mean / high / low price target
    target_hi: float | None
    target_lo: float | None
    cur: str | None
    price_native: float | None
    trend: dict[str, Any]
    upside: float              # % from price to mean target


class FundProfile(TypedDict):
    """cost, country, sectors and top holdings of a fund or share (research.parse_profile)"""
    ter: float | None
    country: str | None
    sector: str | None
    currency: str | None
    sector_weights: dict[str | None, float]
    top_holdings: list[dict[str, Any]]


class NewsItem(TypedDict, total=False):
    title: str | None
    publisher: str | None
    url: str | None
    t: int                     # unix time
    sent: int                  # sentiment: positive words minus negative words


class Factor(TypedDict):
    """one line of the meta score"""
    name: str
    text: str
    pts: float
    max: float


class MetaScore(TypedDict):
    """the rule-based score 0..100 with every factor listed"""
    total: int
    verdict: str
    factors: list[Factor]
    coverage: int


class ResearchResult(TypedDict, total=False):
    """what research.research() returns (the keys the position popup reads)"""
    ok: bool
    sym: str | None
    name: str
    t: int
    notes: list[str]
    prices: list[list[float]]
    splits: list[dict[str, Any]]
    currency: str | None
    long_name: str | None
    metrics: Metrics | None
    analyst: Analyst | None
    news: list[NewsItem]
    score: MetaScore | None

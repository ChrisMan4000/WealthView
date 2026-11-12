"""Securities and crypto: depot positions, trades, FIFO lots and Coinbase holdings."""
from __future__ import annotations
from typing import Any, Literal, TypedDict


Side = Literal["buy", "sell"]                           # direction of a securities trade


LotSide = Side | Literal["in", "out"]                   # a lot trade may also be a transfer in / out (no price)


class AssetGroup(TypedDict):
    """one asset class of the totals (Real estate, Securities, Private equity, Cash, Crypto)"""
    k: str
    v: float


class ParsedPosition(TypedDict):
    """one line of a GLS depot export as gls_parse.parse_depot() reads it (a number that is missing in the file is None)"""
    raw: str
    wkn: str
    qty: float | None
    price: float | None
    value: float | None
    gain_pct: float | None
    gain: float | None


class DepotMeta(TypedDict, total=False):
    """the total lines at the bottom of a depot export"""
    total: float | None
    gain: float | None
    gain_pct: float | None


class _DepotPositionRequired(TypedDict):
    wkn: str
    name: str
    raw: str
    cls: str
    theme: str
    qty: float | None
    price: float | None
    value: float          # loaders.load_depot stores 0.0 for a position without a price
    gain: float | None
    gain_pct: float | None
    cost: float | None
    no_quote: bool


class DepotPosition(_DepotPositionRequired, total=False):
    weight: float
    price_live: float | None
    quote_t: Any
    sym: str | None
    live: bool
    value_snapshot: float
    hist: list[float | None] | None
    trades: list["Trade"]


class _DepotRequired(TypedDict):
    asof: str
    file: str
    total: float
    gain: float | None
    gain_pct: float | None
    cost: float
    positions: list[DepotPosition]
    classes: list[AssetGroup]
    themes: list[AssetGroup]
    top1: float | None
    top3: float | None
    hhi: int | None


class Depot(_DepotRequired, total=False):
    """the depot block of data.json as loaders.load_depot() builds it; the keys below are added later by enrich_depot, refresh and load_depot"""
    age_days: int
    prev: dict[str, Any]
    total_snapshot: float
    n_live: int
    n_total: int
    trades_from: str | None
    n_trades: int


class _TradeRequired(TypedDict):
    d: str             # trade day, ISO
    side: Side
    qty: float
    price: float
    amount: float


class Trade(_TradeRequired, total=False):
    booked: str | None


class Holding(TypedDict, total=False):
    """one Coinbase asset: load_coinbase fills the first block of keys, enrich_crypto / enrich_crypto_cost add the rest"""
    currency: str
    amount: float
    price: float
    eur: float
    hist: list[float | None] | None
    cost: float | None
    gain: float | None
    gain_pct: float | None
    avg_price: float | None
    first_buy: str | None
    cost_known_share: float | None
    lots: list["Lot"] | None
    trades: list["LotTrade"] | None


class CryptoBlock(TypedDict, total=False):
    """the Coinbase block of data.json (load_coinbase, then enrich_crypto / enrich_crypto_cost)"""
    ok: bool
    holdings: list[Holding]
    total_eur: float
    txs: dict[str, list[dict[str, Any]]]       # raw transactions per coin, input of the cost basis
    trades_status: str
    cost: float | None
    gain: float | None
    gain_pct: float | None
    asof: str
    stale: bool                                # True when these are the last known balances (the API call failed)


class LotTrade(TypedDict):
    """one trade as lots.fifo_lots() reads it (side may also be "in" / "out"; price is None for those)"""
    date: str
    side: LotSide
    qty: float
    price: float | None
    fee: float


class KnownLot(TypedDict):
    """one open FIFO lot with a known purchase price"""
    date: str
    qty: float
    price: float
    cost_known: Literal[True]


class UnknownLot(TypedDict):
    """one open FIFO lot that arrived by transfer: no purchase price, never a made-up gain"""
    date: str
    qty: float
    price: None
    cost_known: Literal[False]


Lot = KnownLot | UnknownLot


class RealisedSale(TypedDict):
    date: str
    qty: float
    cost: float | None
    proceeds: float
    gain: float | None


class FifoResult(TypedDict):
    open: list[Lot]
    realised: list[RealisedSale]
    unmatched_sell_qty: float


class CostSummary(TypedDict):
    qty: float
    value: float
    cost: float | None
    gain: float | None
    gain_pct: float | None
    first_buy: str | None
    avg_price: float | None
    cost_known_share: float | None


class _AllowanceUseRequired(TypedDict):
    used: float
    left: float
    taxable: float


class AllowanceUse(_AllowanceUseRequired, total=False):
    year: int

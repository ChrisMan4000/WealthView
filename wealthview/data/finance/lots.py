"""
FIFO lots, cost basis and realised gains (used for Coinbase and the tax view).
A trade is {date: ISO, side: "buy"|"sell"|"in"|"out", qty, price (EUR per unit, None for in/out), fee (EUR)}.
Coins that arrive by transfer ("in") have no known purchase price: they are kept with cost_known False and
never produce a made-up gain.
"""
from __future__ import annotations
from typing import Any
import datetime as dt
import re
from collections import defaultdict

from ...common.config import DEFAULTS
from ...common.parsing import iso, num, round2
from ...common.types.bookings import BookingRow
from ...common.types.depot import AllowanceUse, CostSummary, FifoResult, KnownLot, Lot, LotSide, LotTrade, RealisedSale, Trade, UnknownLot
EPS = 1e-12


def _price(t: LotTrade) -> float:
    """the unit price of a buy / sell trade (only transfers in / out may have none)"""
    price = t["price"]
    if price is None:
        raise ValueError(f"{t['side']} trade on {t['date']} has no price")
    return price


def _consume(open_lots: list[Lot], qty: float) -> tuple[float, bool, float, float]:
    """takes `qty` from the oldest open lots (in place) -> (cost of what was taken, cost fully known, quantity consumed, quantity left over)"""
    left, cost, known, consumed = qty, 0.0, True, 0.0
    while left > EPS and open_lots:
        lot = open_lots[0]
        take = min(left, lot["qty"])
        if lot["cost_known"]:
            cost += take * lot["price"]
        else:
            known = False
        consumed += take
        lot["qty"] -= take
        left -= take
        if lot["qty"] <= EPS:
            open_lots.pop(0)
    return cost, known, consumed, left


def _sell_or_send_out(open_lots: list[Lot], realised: list[RealisedSale], t: LotTrade, qty: float, fee: float) -> float:
    """Take a sale or a transfer out from the oldest lots; a real sale is added to `realised`. -> quantity that no lot covered"""
    cost, known, consumed, left = _consume(open_lots, qty)
    if t["side"] == "sell" and consumed > EPS:
        proceeds = consumed * _price(t) - fee * (consumed / qty)
        realised.append({"date": t["date"], "qty": consumed,
                         "cost": cost if known else None, "proceeds": proceeds,
                         "gain": proceeds - cost if known else None})
    return left


def fifo_lots(trades: list[LotTrade]) -> FifoResult:
    open_lots: list[Lot] = []
    realised: list[RealisedSale] = []
    unmatched = 0.0
    # same day: buys and received coins first, so a sale listed before its buy in the file still finds its lot
    for t in sorted(trades or [], key=lambda x: (x["date"], x["side"] in ("sell", "out"))):
        side, qty = t["side"], float(t["qty"])
        fee = float(t.get("fee") or 0.0)
        if qty <= 0:
            continue
        if side == "buy":
            open_lots.append(KnownLot(date=t["date"], qty=qty, price=_price(t) + fee / qty, cost_known=True))
        elif side == "in":
            open_lots.append(UnknownLot(date=t["date"], qty=qty, price=None, cost_known=False))
        elif side in ("sell", "out"):
            left = _sell_or_send_out(open_lots, realised, t, qty, fee)
            if left > EPS:
                unmatched += left
    return {"open": open_lots, "realised": realised, "unmatched_sell_qty": unmatched}


def trim_to_balance(open_lots: list[Lot], balance: float) -> list[Lot]:
    """Coins that left through a route we do not map (exchange deposit, ...): the open lots can then hold more than
    the wallet. Remove the surplus first-in-first-out so the gain is not computed on coins that are gone."""
    surplus = sum(l["qty"] for l in open_lots) - balance
    out: list[Lot] = []
    for l in open_lots:
        if surplus > EPS:
            cut = min(l["qty"], surplus)
            surplus -= cut
            if l["qty"] - cut <= EPS:
                continue
            l = l.copy()
            l["qty"] -= cut
        out.append(l)
    return out


def cost_summary(open_lots: list[Lot], price_now: float) -> CostSummary:
    qty = sum(l["qty"] for l in open_lots)
    known: list[KnownLot] = []
    for l in open_lots:
        if l["cost_known"]:
            known.append(l)
    kqty = sum(l["qty"] for l in known)
    out: CostSummary = {"qty": qty, "value": qty * price_now, "cost": None, "gain": None, "gain_pct": None,
                        "first_buy": None, "avg_price": None, "cost_known_share": (kqty / qty) if qty > EPS else None}
    if known and kqty > EPS:
        cost = sum(l["qty"] * l["price"] for l in known)
        out["cost"] = cost
        gain = kqty * price_now - cost
        out["gain"] = gain
        out["avg_price"] = cost / kqty
        out["first_buy"] = min(l["date"] for l in known)
        out["gain_pct"] = gain / cost * 100.0 if cost > 0 else None
    return out


def realised_by_year(realised: list[RealisedSale]) -> dict[int, float]:
    out: dict[int, float] = {}
    for r in realised or []:
        gain = r.get("gain")
        if gain is None:
            continue
        y = int(str(r["date"])[:4])
        out[y] = out.get(y, 0) + gain
    return out


def allowance_use(realised_year: float, allowance: float = DEFAULTS["tax"]["allowance_eur"]) -> AllowanceUse:
    used = min(max(realised_year, 0), allowance)
    return {"used": used, "left": allowance - used, "taxable": max(realised_year - allowance, 0)}


# ------------------------------------------------------------ Coinbase transactions -> trades
FIAT = {"EUR", "USD", "GBP", "CHF"}          # cash wallets are not crypto holdings
_REWARD_WORDS = ("reward", "interest", "payout")


def _trade_row(t: dict[str, Any], ty: str, qty: float, priced: bool, unit: float | None) -> LotTrade | None:
    """one Coinbase transaction -> a trade dict for fifo_lots(), or None when it is ignored"""
    def row(side: LotSide, q: float, price: float | None) -> LotTrade:
        return {"date": t["date"], "side": side, "qty": q, "price": price, "fee": 0.0}

    if ty in ("buy", "sell", "trade", "advanced_trade_fill"):
        if (ty == "buy" and qty < 0) or (ty == "sell" and qty > 0):
            return None
        if priced:
            return row("sell" if qty < 0 else "buy", abs(qty), unit)
        return row("in" if qty > 0 else "out", abs(qty), None)
    if any(w in ty for w in _REWARD_WORDS) and qty > 0:
        return row("buy" if priced else "in", qty, unit)
    if ty == "send" or any(w in ty for w in _REWARD_WORDS):
        return row("in" if qty > 0 else "out", abs(qty), None)
    return None


def trades_from_cb_transactions(raw: list[dict[str, Any]] | None) -> list[LotTrade]:
    """Map flattened Coinbase transactions {type, date, qty (signed), native (signed EUR value), native_cur}
    to trades for fifo_lots().
      buy / sell / trade        priced with the native EUR value (fees are part of it); the euro leg of a purchase
                                (buy with negative qty, sell with positive qty) is ignored
      staking rewards, interest priced at their EUR value when received (that is also their tax cost basis)
      send                      in / out without a price: the cost is unknown, never a made-up gain
      staking_transfer etc.     moves between your own wallets: ignored, so the purchase lots stay where they are
    Fiat movements and unknown types are ignored."""
    out: list[LotTrade] = []
    for t in raw or []:
        ty, qty = str(t.get("type", "")).lower(), float(t.get("qty") or 0)
        if qty == 0 or "staking_transfer" in ty:
            continue
        native, cur = t.get("native"), t.get("native_cur")
        priced = native is not None and cur == "EUR"
        unit = abs(float(native)) / abs(qty) if native is not None and priced else None
        r = _trade_row(t, ty, qty, priced, unit)
        if r is not None:
            out.append(r)
    return out


TRADE_RX = re.compile(r"WERTPAPIERABRECHNUNG\s+(KAUF|VERKAUF)\s+(.*?)WKN\s+([A-Z0-9]{6})\s*/\s*(\S+).*?HANDELSTAG\s+(\d{2}\.\d{2}\.\d{4})\s+MENGE\s+([\d.,]+)\s+KURS\s+([\d.,]+)(?:.*?AUFTRAGSNR\.?\s+(\d+))?", re.S)


def parse_trades(rows: list[BookingRow]) -> dict[str, list[Trade]]:
    """Securities buys/sells from the GLS bookings (text 'WERTPAPIERABRECHNUNG KAUF/VERKAUF ... WKN ... HANDELSTAG ... MENGE ... KURS ...').
    Returns {wkn: [trade, ...]} sorted by date; trade = dict(d, side, qty, price, amount). Only exists for the period the bank exports cover."""
    out: defaultdict[str, list[Trade]] = defaultdict(list)
    seen: set[tuple[str, str, str, str, str]] = set()
    for r in rows:
        p = r["purpose"]
        if "WERTPAPIERABRECHNUNG" not in p or "STEUERAUSGLEICH" in p[:120]:
            continue
        m = TRADE_RX.search(p)
        if not m:
            continue
        side, _, wkn, _, day, qty, kurs, oid = m.groups()
        key = (oid or "", wkn, day, qty, side)
        if key in seen:
            continue
        seen.add(key)
        d = dt.datetime.strptime(day, "%d.%m.%Y").date()
        q = num(qty)
        pr = num(kurs)
        if q is None or pr is None:
            continue
        out[wkn].append(Trade(d=d.isoformat(), side="buy" if side == "KAUF" else "sell", qty=q, price=pr, amount=round2(abs(r["amount"])), booked=iso(r["date"])))
    for w in out:
        out[w].sort(key=lambda t: t["d"])
    return dict(out)

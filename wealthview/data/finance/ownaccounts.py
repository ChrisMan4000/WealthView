"""Which bookings are internal transfers or credit-card settlements (neither income nor spending), and how a booking counts
in the cash flow (flow_kind). Single home for these rules and for the one walk over the bookings (cash_flow_events); bookings.py and gls_block.py both use them."""
from __future__ import annotations
from typing import Literal
from collections.abc import Iterator

from .categories import invest_rx
from ...common.config import own_names
from ...common.timeutil import month_key
from ...common.types.bookings import FLOW_KINDS, BookingRow

FlowKind = Literal["skip", "invest", "flow"]
EventKind = Literal["invest", "income", "expense"]


class OwnAccounts:
    def __init__(self, rows: list[BookingRow]) -> None:
        self.own_ibans = {r["iban"] for r in rows if r["iban"]}
        self.card_ibans = {r["iban"] for r in rows if r["kind"] == "card" and r["iban"]}
        self.names = own_names()

    def internal(self, r: BookingRow) -> bool:
        if r["cp_iban"] and r["cp_iban"] in self.own_ibans:
            return True
        if any(n in r["counterparty"].lower() for n in self.names):
            return True
        return r["typ"].lower().startswith("umbuchung")

    def card_settlement(self, r: BookingRow) -> bool:
        if r["kind"] != "giro":
            return False
        t = (r["typ"] + " " + r["purpose"] + " " + r["counterparty"]).lower()
        return r["cp_iban"] in self.card_ibans or "kreditkarte" in t

    def is_external(self, r: BookingRow) -> bool:
        """True for a giro / card booking that is not an own transfer and not a card settlement."""
        return r["kind"] in FLOW_KINDS and not self.internal(r) and not self.card_settlement(r)

    def flow_kind(self, r: BookingRow) -> FlowKind:
        """How a booking counts in the cash flow: 'skip' (other account kind, own transfer, card settlement or card repayment),
        'invest' (buying/selling investments, not spending) or 'flow' (real income or spending)."""
        if not self.is_external(r):
            return "skip"
        rc = r["cat"].lower()
        if rc.startswith("kreditkartenabrechnung") or (r["kind"] == "card" and r["amount"] > 0):
            return "skip"
        if rc.startswith("wertpapiere") or invest_rx().search(r["counterparty"] + " " + r["purpose"][:80]):
            return "invest"
        return "flow"


def cash_flow_events(rows: list[BookingRow], own: OwnAccounts) -> Iterator[tuple[BookingRow, str, EventKind]]:
    """The one walk over the bookings for both cash-flow models: (booking, month key like '2024-05', kind) for every booking that counts.
    kind is 'invest' (investing, not spending), 'income' (amount > 0) or 'expense'. Own transfers and card settlements are left out."""
    for r in rows:
        fk = own.flow_kind(r)
        if fk == "skip":
            continue
        mk = month_key(r["date"])
        yield r, mk, ("invest" if fk == "invest" else "income" if r["amount"] > 0 else "expense")

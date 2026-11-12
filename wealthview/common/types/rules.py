"""Records of the category-correction pop-up (v1.15)."""
from __future__ import annotations
from typing import TypedDict


class RuleRow(TypedDict):
    """one saved rule: kind 'merchant' (the merchant name as shown in WealthView) or 'text' (a keyword in payee or purpose)"""
    id: int
    kind: str
    pattern: str
    category: str
    created: str

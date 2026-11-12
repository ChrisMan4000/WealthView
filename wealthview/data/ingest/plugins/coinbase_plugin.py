"""Source plugin 'coinbase'. Coinbase is read from the API (loaders.load_coinbase), there is no Coinbase CSV parser today. The only Coinbase *file* is the
JSON the loader keeps as its last-known-balances cache (and coinbase_fetch.mjs output saved to disk): {"ok": true, "holdings": [...], ...}.
detect() recognises that JSON; parse() returns its holdings. Nothing here calls the network."""
from __future__ import annotations
import json
import re
from typing import Any
from .base import head_text, register

_HOLDINGS = re.compile(r'"holdings"\s*:\s*\[')


class CoinbasePlugin:
    name = "coinbase"

    def detect(self, path: str, head: bytes) -> float:
        text = head_text(head).lstrip()
        if not text.startswith("{"):
            return 0.0
        if _HOLDINGS.search(text):
            return 0.9 if '"total_eur"' in text or '"ok"' in text else 0.7
        return 0.0

    def parse(self, path: str) -> list[dict[str, Any]]:
        """The holdings of a Coinbase block file; [] when the file has none. Raises ValueError (JSONDecodeError) for non-JSON."""
        with open(path, "rb") as f:
            data = json.loads(f.read().decode("utf-8-sig"))
        h = data.get("holdings") if isinstance(data, dict) else None
        return list(h) if isinstance(h, list) else []


register(CoinbasePlugin())

"""WealthView v1.21: the services a place can be read from through an API instead of a folder of exports. One table, used by the setup screen (which
fields to ask for) and by the refresh (which reader to run). Every connection is read-only: WealthView only asks for balances.
`ready` = the refresh really reads it today; a connector that is not ready only stores its details. Standard library only."""
from __future__ import annotations
import os
from typing import Any, TypedDict


class Field(TypedDict):
    key: str
    label: str
    secret: bool          # typed as a password field and never shown again
    hint: str


class Connector(TypedDict):
    id: str
    label: str
    sections: tuple[str, ...]
    fields: list[Field]
    ready: bool
    note: str
    env: tuple[str, ...]  # environment variables that can supply the keys instead (older setups)


def _f(key: str, label: str, secret: bool = False, hint: str = "") -> Field:
    return Field(key=key, label=label, secret=secret, hint=hint)


_VIEW = "Create a key that may only VIEW (read) - never one that may trade or withdraw."
CONNECTORS: tuple[Connector, ...] = (
    Connector(id="coinbase", label="Coinbase", sections=("crypto",), ready=True, env=("COINBASE_KEY_NAME", "COINBASE_KEY_SECRET"),
              fields=[_f("key_name", "API key name", hint="organizations/.../apiKeys/..."), _f("key_secret", "API secret", True)],
              note=_VIEW + " Coinbase: Settings > API > new key with the Ed25519 signature (not ECDSA) and the permission View."),
    Connector(id="binance", label="Binance", sections=("crypto",), ready=True, env=(),
              fields=[_f("api_key", "API key"), _f("api_secret", "Secret key", True)],
              note=_VIEW + " Binance: Account > API Management > create API (system generated), leave only \"Enable Reading\" ticked."),
    Connector(id="kraken", label="Kraken", sections=("crypto",), ready=True, env=(),
              fields=[_f("api_key", "API key"), _f("private_key", "Private key", True)],
              note=_VIEW + " Kraken: Settings > API > create key with only the permission \"Query funds\"."),
    Connector(id="fints", label="FinTS / HBCI (most German banks)", sections=("bank", "investment"), ready=False, env=(),
              fields=[_f("blz", "Bank code (BLZ)", hint="8 digits"), _f("url", "FinTS address of the bank", hint="https://..."),
                      _f("login", "Online banking login name"), _f("product_id", "FinTS product ID", hint="from the registration at fints.org")],
              note="The connection details are saved now. Reading the bank through FinTS is not switched on yet in this version: it needs a registered "
                   "FinTS product ID and a first sign-in confirmed in your bank app. Until then, keep using the folder of exports. No PIN is asked for here."),
)
BY_ID = {c["id"]: c for c in CONNECTORS}


def for_section(section: str) -> list[Connector]:
    return [c for c in CONNECTORS if section in c["sections"]]


def env_ready(c: Connector) -> bool:
    """True when the connector's keys are already supplied through environment variables on this computer."""
    return bool(c["env"]) and all(os.environ.get(v) for v in c["env"])


def public(c: Connector) -> dict[str, Any]:
    """What the setup screen may know about a connector."""
    return dict(id=c["id"], label=c["label"], sections=list(c["sections"]), fields=c["fields"], ready=c["ready"], note=c["note"], env_ready=env_ready(c))


def clean_keys(c: Connector, raw: Any, *, required: bool = True) -> dict[str, str]:
    """The typed values of the connector's fields, trimmed. ValueError naming the first empty field when `required`."""
    src = raw if isinstance(raw, dict) else {}
    out: dict[str, str] = {}
    for f in c["fields"]:
        v = str(src.get(f["key"]) or "").strip()
        if len(v) > 600:
            raise ValueError(f"{f['label']} is too long")
        if v:
            out[f["key"]] = v
        elif required:
            raise ValueError(f"{f['label']} is missing")
    return out

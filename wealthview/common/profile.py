"""WealthView - profile.json: what this installation shows (edition, screen tier, asset classes, sources, optional modules, tax country).
Without a profile.json the legacy profile applies, so an existing private install behaves exactly as before."""
from __future__ import annotations
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import fileio, paths

log = logging.getLogger("wealthview")

TIERS = ("ultrawide", "desktop", "laptop", "compact")
MODULE_KEYS = ("worldfund", "wiwin", "loan", "apartment")
_ASSET_CLASSES = ["realEstate", "securities", "privateEquity", "cash", "crypto"]


_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


@dataclass
class SourceSpec:
    """One data source: kind of parser, the folder it is read from (read only), the entity it belongs to and an optional column mapping."""
    kind: str
    folder: str
    entity: str
    mapping: dict[str, Any] | None = None


@dataclass
class Profile:
    """The installer's choices, read by module gating, layout and the installer engine."""
    edition: str
    tier: str
    asset_classes: list[str]
    sources: list[SourceSpec]
    modules: dict[str, bool]
    tax_country: str
    home: dict[str, Any]
    chat: bool
    jarvis_url: str | None = None

    @classmethod
    def legacy(cls) -> Profile:
        """The profile of an install without profile.json: everything on, as before the installers."""
        return cls("private", "ultrawide", list(_ASSET_CLASSES), [], {k: True for k in MODULE_KEYS}, "DE", {}, True, None)

    def validate(self) -> None:
        """Raise ValueError for an unknown tier or module key."""
        if self.tier not in TIERS:
            raise ValueError(f"unknown tier {self.tier!r} (expected one of {', '.join(TIERS)})")
        bad = [k for k in self.modules if k not in MODULE_KEYS]
        if bad:
            raise ValueError(f"unknown module key(s) {bad!r}")

    def to_dict(self) -> dict[str, Any]:
        """Plain dict for JSON."""
        return asdict(self)

    @staticmethod
    def _bool(v: Any, what: str) -> bool:
        """A JSON boolean; also 0/1 and the strings true/false/yes/no/on/off/1/0 (bool("false") would be True). Anything else is an error."""
        if isinstance(v, bool):
            return v
        if isinstance(v, int) and v in (0, 1):
            return bool(v)
        if isinstance(v, str) and v.strip().lower() in _TRUE | _FALSE:
            return v.strip().lower() in _TRUE
        raise ValueError(f"{what} must be true or false")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Profile:
        """Build a validated profile from parsed JSON; missing keys take the legacy values. Raises ValueError/TypeError on bad data."""
        base = cls.legacy()
        if not isinstance(d, dict):
            raise ValueError("profile.json must contain a JSON object")
        mods = dict(base.modules)
        mods.update({k: cls._bool(v, f"modules.{k}") for k, v in (d.get("modules") or {}).items()})
        ac = d.get("asset_classes", base.asset_classes)
        if not isinstance(ac, (list, tuple)):
            raise ValueError("asset_classes must be a list")
        p = cls(
            edition=str(d.get("edition", base.edition)),
            tier=str(d.get("tier", base.tier)),
            asset_classes=[str(x) for x in ac],
            sources=[SourceSpec(str(s["kind"]), str(s["folder"]), str(s["entity"]), s.get("mapping")) for s in d.get("sources", [])],
            modules=mods,
            tax_country=str(d.get("tax_country", base.tax_country)),
            home=dict(d.get("home") or {}),
            chat=cls._bool(d.get("chat", base.chat), "chat"),
            jarvis_url=d.get("jarvis_url"),
        )
        p.validate()
        return p


def _resolve(path: str | None) -> Path:
    return Path(path) if path else paths.data_path("profile.json")


def load_profile(path: str | None = None) -> Profile:
    """The profile from `path` (default data/profile.json). Missing file: legacy. Corrupt or invalid file: logged, legacy."""
    f = _resolve(path)
    try:
        text = f.read_text("utf-8-sig")
    except FileNotFoundError:
        return Profile.legacy()
    except OSError as exc:
        log.warning("profile.json unreadable (%s): using the legacy profile", exc)
        return Profile.legacy()
    try:
        return Profile.from_dict(json.loads(text))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        log.warning("profile.json invalid (%s): using the legacy profile", exc)
        return Profile.legacy()


def save_profile(p: Profile, path: str | None = None) -> None:
    """Validate and write the profile atomically (default data/profile.json)."""
    p.validate()
    fileio.write_atomic(_resolve(path), json.dumps(p.to_dict(), indent=2, ensure_ascii=False) + "\n")

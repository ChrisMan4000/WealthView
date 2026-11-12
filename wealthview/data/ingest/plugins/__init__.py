"""WealthView source plugins: import this package to get REGISTRY filled with the built-in plugins.
SourcePlugin / REGISTRY / detect_best / register live in base.py (so plugin modules can register without importing the package)."""
from __future__ import annotations
from .base import HEAD_BYTES, MIN_CONFIDENCE, REGISTRY, SourcePlugin, detect_best, register       # noqa: F401
from . import gls, gls_depot, paypal_plugin, coinbase_plugin, csv_plugin       # noqa: F401  (each registers itself; a new plugin is added here)

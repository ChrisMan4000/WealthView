"""PIN / password hashing shared by the app sign-in (wealthview.app.auth) and the installer engine (wvsetup)."""
from __future__ import annotations
from typing import Any
import hashlib, secrets, unicodedata

PIN_ITERATIONS = 200_000


def hash_pin(pin: Any, salt: bytes | None = None, iterations: int = PIN_ITERATIONS) -> str:
    """Salted PBKDF2-SHA256 of the PIN (Unicode NFC-normalised first, so composed and decomposed accents match), stored as
    'pbkdf2$iterations$salt$hash' (config.json -> pin_hash)."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", unicodedata.normalize("NFC", str(pin)).encode(), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${h.hex()}"

"""WealthView sign-in: PIN hashing, the `python server.py --set-pin` command, session tokens and the lock-out after wrong PINs."""
from __future__ import annotations
from typing import Any, NamedTuple
import getpass, hashlib, hmac, json, secrets, threading, time, unicodedata
from ..common import audit, config, fileio, paths
from ..common.timeutil import HOUR_S

MAX_PIN_FAILS = 5
WRONG_PIN_MESSAGE = "wrong PIN"
PIN_LOCKOUT_S = 60
WRONG_PIN_DELAY_S = 0.8     # a wrong PIN is answered with this delay
TOKEN_TTL = 12 * HOUR_S
PIN_ITERATIONS = 200_000
MAX_PIN_LENGTH = 1024


def hash_pin(pin: Any, salt: bytes | None = None, iterations: int = PIN_ITERATIONS) -> str:
    """Salted PBKDF2-SHA256 of the PIN (Unicode NFC-normalised first, so composed and decomposed accents match), stored as
    'pbkdf2$iterations$salt$hash' (config.json -> pin_hash)."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", unicodedata.normalize("NFC", str(pin)).encode(), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${h.hex()}"


def pin_setup_error(cfg: dict[str, Any]) -> str | None:
    """None when config.json has a usable pin_hash; otherwise a clear message telling the owner how to set the PIN."""
    if cfg.get("pin_hash"):
        return None
    if cfg.get("pin_sha256"):
        return "the old PIN format is no longer supported - set the PIN again: run 'python server.py --set-pin'"
    return "no PIN is set yet - run 'python server.py --set-pin' once"


def pin_ok(pin: Any) -> bool:
    """True when `pin` matches config.json -> pin_hash (salted). No pin_hash means nobody gets in."""
    stored = config.load_config().get("pin_hash")
    if not stored or len(str(pin)) > MAX_PIN_LENGTH:        # an oversized secret is simply wrong (never hashed)
        return False
    try:
        _, iters, salt, _ = stored.split("$")
        return hmac.compare_digest(hash_pin(pin, bytes.fromhex(salt), int(iters)), stored)
    except ValueError:                                      # malformed stored hash: nobody gets in
        return False


def set_pin() -> int:
    """Ask for a new PIN (typed twice, not shown) and store its salted hash in config.json -> pin_hash. Returns the exit code."""
    pin = getpass.getpass("New PIN: ")
    if not pin or pin != getpass.getpass("Same PIN again: "):
        print("The PINs are empty or different - nothing changed.")
        return 1
    path = paths.BASE / "config.json"
    try:
        cfg = json.loads(path.read_text("utf-8-sig")) if path.exists() else {}
        cfg["pin_hash"] = hash_pin(pin)
        cfg.pop("pin_sha256", None)                         # the old unsalted field is not used any more
        fileio.write_atomic(path, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError) as exc:
        print("Could not write config.json:", exc)
        return 1
    print("PIN saved. Start WealthView again.")
    return 0


class PinResult(NamedTuple):
    """Outcome of one PIN attempt: the HTTP code, the reply for the page, and whether the PIN was wrong (decides the guessing delay)."""
    code: int
    reply: dict[str, Any]
    wrong: bool = False


class AuthState:
    """Who is signed in: session tokens (token -> expiry time) and the failed-PIN counter with its lock-out."""

    def __init__(self) -> None:
        self.tokens: dict[str, float] = {}
        self.fail_count = 0
        self.locked_until = 0.0
        self.token_lock = threading.Lock()      # session tokens only (held for a dictionary lookup, never for slow work)
        self.pin_lock = threading.Lock()        # one PIN attempt at a time (the PIN check is slow on purpose); guards the fail counter

    def purge_tokens(self, now: float) -> None:
        """Drop expired session tokens so the table cannot grow without limit."""
        for t in [t for t, exp in self.tokens.items() if exp <= now]:
            self.tokens.pop(t, None)

    def is_signed_in(self, token: str) -> bool:
        """True when `token` is a session token that has not expired."""
        with self.token_lock:
            exp = self.tokens.get(token)
        return bool(exp and exp > time.time())

    def sign_out(self, token: str) -> None:
        """The token stops working at once."""
        with self.token_lock:
            self.tokens.pop(token, None)

    def attempt(self, pin: Any) -> PinResult:
        """Counts the attempt and returns a PinResult (HTTP code, reply, wrong-PIN flag). pin_lock makes attempts go one at a time (so parallel guesses
        cannot get around the lock-out); token_lock is only taken for the quick token update, so other requests never wait for the slow hashing."""
        now = time.time()
        with self.pin_lock:
            if self.locked_until > now:
                audit.record("unlock_refused_lockout")
                return PinResult(429, {"ok": False, "error": "too many tries, wait a minute"})
            problem = pin_setup_error(config.load_config())      # may raise on an unreadable config.json: the HTTP handler turns that into {ok: false, error}
            if problem:
                return PinResult(200, {"ok": False, "error": problem})
            if pin_ok(pin):
                self.fail_count = 0
                audit.record("unlock_ok")
                tok = secrets.token_hex(16)
                with self.token_lock:
                    self.purge_tokens(now)
                    self.tokens[tok] = now + TOKEN_TTL
                return PinResult(200, {"ok": True, "token": tok})
            self.fail_count += 1
            audit.record("unlock_failed", f"try {self.fail_count}")
            if self.fail_count >= MAX_PIN_FAILS:
                self.fail_count, self.locked_until = 0, now + PIN_LOCKOUT_S
                audit.record("lockout_started", f"{PIN_LOCKOUT_S} s")
        return PinResult(200, {"ok": False, "error": WRONG_PIN_MESSAGE}, wrong=True)

    def check_pin(self, pin: Any) -> tuple[int, dict[str, Any]]:
        """attempt() as a plain (HTTP code, reply) pair."""
        res = self.attempt(pin)
        return res.code, res.reply

    def unlock(self, pin: Any) -> tuple[int, dict[str, Any]]:
        """attempt, then the short pause after a wrong PIN (no lock is held while waiting). The pause depends on the typed result,
        not on the wording of the message."""
        res = self.attempt(pin)
        if res.wrong:
            time.sleep(WRONG_PIN_DELAY_S)       # slows guessing down
        return res.code, res.reply

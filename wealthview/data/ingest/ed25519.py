"""Ed25519 signatures in plain Python (RFC 8032, section 6 - the reference algorithm). WealthView v1.22 signs the Coinbase API token with it, so the
Coinbase connection needs neither Node.js nor an extra package. It is slow compared with a C library (a few milliseconds per signature) and takes no
care about timing side channels - fine for signing a handful of requests on the user's own PC, not meant for anything else. Standard library only."""
from __future__ import annotations
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
_SQRT_M1 = pow(2, (P - 1) // 4, P)
Point = tuple[int, int, int, int]


def _sha512(b: bytes) -> bytes:
    return hashlib.sha512(b).digest()


def _add(a: Point, b: Point) -> Point:
    A, B = (a[1] - a[0]) * (b[1] - b[0]) % P, (a[1] + a[0]) * (b[1] + b[0]) % P
    C, Dd = 2 * a[3] * b[3] * D % P, 2 * a[2] * b[2] % P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def _mul(s: int, p: Point) -> Point:
    q: Point = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _recover_x(y: int, sign: int) -> int:
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P)
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * _SQRT_M1 % P
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * pow(5, P - 2, P) % P
_GX = _recover_x(_GY, 0)
G: Point = (_GX, _GY, 1, _GX * _GY % P)


def _compress(p: Point) -> bytes:
    zinv = pow(p[2], P - 2, P)
    x, y = p[0] * zinv % P, p[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _expand(seed: bytes) -> tuple[int, bytes]:
    if len(seed) != 32:
        raise ValueError("an Ed25519 secret is 32 bytes")
    h = _sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed: bytes) -> bytes:
    a, _ = _expand(seed)
    return _compress(_mul(a, G))


def sign(seed: bytes, msg: bytes) -> bytes:
    """The 64-byte signature of msg with the 32-byte secret seed."""
    a, prefix = _expand(seed)
    A = _compress(_mul(a, G))
    r = int.from_bytes(_sha512(prefix + msg), "little") % L
    Rs = _compress(_mul(r, G))
    h = int.from_bytes(_sha512(Rs + A + msg), "little") % L
    return Rs + int.to_bytes((r + h * a) % L, 32, "little")

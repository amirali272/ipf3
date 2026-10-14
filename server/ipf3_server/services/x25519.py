"""X25519 key generation for Xray REALITY (RFC 7748), without extra dependencies.

Keys use the same encoding as `xray x25519`: raw 32 bytes, base64url without padding."""

from __future__ import annotations

import base64
import secrets

_P = 2**255 - 19
_A24 = 121665


def _decode_scalar(k: bytes) -> int:
    b = bytearray(k)
    b[0] &= 248
    b[31] &= 127
    b[31] |= 64
    return int.from_bytes(b, "little")


def _x25519(k: bytes, u: bytes) -> bytes:
    scalar = _decode_scalar(k)
    x1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in reversed(range(255)):
        bit = (scalar >> t) & 1
        swap ^= bit
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a, b = (x2 + z2) % _P, (x2 - z2) % _P
        aa, bb = a * a % _P, b * b % _P
        e = (aa - bb) % _P
        c, d = (x3 + z3) % _P, (x3 - z3) % _P
        da, cb = d * a % _P, c * b % _P
        x3 = (da + cb) ** 2 % _P
        z3 = x1 * (da - cb) ** 2 % _P
        x2 = aa * bb % _P
        z2 = e * (aa + _A24 * e) % _P
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def raw_private() -> bytes:
    """A random clamped Curve25519 scalar, as raw bytes (RFC 7748)."""
    priv = bytearray(secrets.token_bytes(32))
    priv[0] &= 248
    priv[31] &= 127
    priv[31] |= 64
    return bytes(priv)


def raw_public(priv: bytes) -> bytes:
    if len(priv) != 32:
        raise ValueError("private key must be 32 bytes")
    return _x25519(priv, (9).to_bytes(32, "little"))


def public_key(private_b64: str) -> str:
    return _b64(raw_public(_unb64(private_b64)))


def generate_keypair() -> tuple[str, str]:
    """base64url, no padding — the encoding `xray x25519` and REALITY use."""
    priv = raw_private()
    return _b64(priv), _b64(raw_public(priv))

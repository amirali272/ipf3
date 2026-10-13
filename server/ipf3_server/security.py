from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import get_settings
from .models import Role

_ph = PasswordHasher()  # argon2id with library defaults (RFC 9106 low-memory profile)

# A valid hash used to equalise timing when the username does not exist.
_DUMMY_HASH = _ph.hash(secrets.token_hex(16))

ROLE_LEVEL = {Role.viewer: 0, Role.operator: 1, Role.admin: 2}

SESSION_COOKIE = "ipf3_session"
CSRF_COOKIE = "ipf3_csrf"
CSRF_HEADER = "x-ipf3-csrf"


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _ph.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


def validate_password_strength(password: str) -> None:
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    if len(password) > 256:
        raise ValueError("password too long")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        raise ValueError(
            "password must contain at least three of: lowercase, uppercase, digit, symbol"
        )


def create_session_token(user_id: int, session_version: int) -> tuple[str, datetime]:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.session_ttl_minutes)
    payload = {
        "sub": str(user_id),
        "sv": session_version,
        "exp": exp,
        "iat": datetime.now(timezone.utc),
        "typ": "session",
    }
    return jwt.encode(payload, s.secret_key, algorithm="HS256"), exp


def decode_session_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=["HS256"],
            options={"require": ["exp", "sub", "sv"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "session":
        return None
    return payload


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Tokens are 256-bit random values, so a fast unsalted hash is sufficient
    (brute force is infeasible) and survives rotation of IPF3_SECRET_KEY."""
    return hashlib.sha256(token.encode()).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())

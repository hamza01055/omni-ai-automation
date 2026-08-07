"""Security primitives: password hashing, JWTs, credential encryption, webhook signatures.

Design notes
------------
* Passwords use Argon2id — memory-hard, and the current OWASP recommendation.
* Access tokens are short-lived and stateless; refresh tokens carry a ``jti``
  that is checked against a Redis denylist so logout and rotation are real.
* Channel credentials (Meta/X tokens) are encrypted with Fernet before they
  touch the database, so a database dump alone does not leak customer tokens.
* Webhook signatures are compared with ``hmac.compare_digest`` to avoid
  timing oracles.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.errors import AuthenticationError

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


# ── Passwords ────────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    """True when Argon2 parameters have moved on since this hash was made."""
    return _hasher.check_needs_rehash(hashed)


# ── JWT ──────────────────────────────────────────────────────────────────


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    *, user_id: str, organization_id: str, role: str, email: str
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.access_token_ttl_minutes)
    token = _encode(
        {
            "sub": str(user_id),
            "org": str(organization_id),
            "role": role,
            "email": email,
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": uuid.uuid4().hex,
        }
    )
    return token, expires


def create_refresh_token(*, user_id: str, organization_id: str) -> tuple[str, str, datetime]:
    """Return ``(token, jti, expires_at)``. The jti is stored for revocation."""
    now = datetime.now(UTC)
    expires = now + timedelta(days=settings.refresh_token_ttl_days)
    jti = uuid.uuid4().hex
    token = _encode(
        {
            "sub": str(user_id),
            "org": str(organization_id),
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": jti,
        }
    )
    return token, jti, expires


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Session expired. Sign in again.", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid authentication token.") from exc

    if payload.get("type") != expected_type:
        raise AuthenticationError("Wrong token type for this endpoint.")
    return payload


# ── Credential encryption at rest ────────────────────────────────────────


def _fernet() -> Fernet:
    if not settings.credential_encryption_key:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY is not set — channel credentials cannot be stored."
        )
    return Fernet(settings.credential_encryption_key.encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError(
            "Stored credential could not be decrypted. "
            "CREDENTIAL_ENCRYPTION_KEY may have been rotated without re-encrypting."
        ) from exc


# ── Webhook signature verification ───────────────────────────────────────


def verify_meta_signature(raw_body: bytes, header_value: str | None, app_secret: str) -> bool:
    """Verify Meta's ``X-Hub-Signature-256`` header (WhatsApp, Instagram, Facebook)."""
    if not header_value or not app_secret:
        return False
    prefix, _, provided = header_value.partition("=")
    if prefix != "sha256" or not provided:
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def verify_x_signature(raw_body: bytes, header_value: str | None, secret: str) -> bool:
    """Verify X's base64 HMAC-SHA256 webhook signature header."""
    import base64

    if not header_value or not secret:
        return False
    provided = header_value.removeprefix("sha256=")
    expected = base64.b64encode(
        hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, provided)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())

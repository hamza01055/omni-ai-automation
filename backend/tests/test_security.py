"""Password hashing, JWT lifecycle, encryption and signature verification."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.core.errors import AuthenticationError
from app.core.security import (
    create_access_token, create_refresh_token, decode_token, decrypt_secret,
    encrypt_secret, hash_password, verify_meta_signature, verify_password,
)


def test_password_round_trip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password entirely", hashed)


def test_password_hashes_are_salted():
    assert hash_password("same") != hash_password("same")


def test_access_token_carries_org_scope():
    token, _ = create_access_token(
        user_id="u-1", organization_id="o-1", role="admin", email="a@b.co"
    )
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "u-1"
    assert payload["org"] == "o-1"
    assert payload["role"] == "admin"


def test_refresh_token_rejected_where_access_expected():
    token, _jti, _exp = create_refresh_token(user_id="u-1", organization_id="o-1")
    with pytest.raises(AuthenticationError):
        decode_token(token, expected_type="access")


def test_tampered_token_rejected():
    token, _ = create_access_token(
        user_id="u-1", organization_id="o-1", role="viewer", email="a@b.co"
    )
    head, body, sig = token.split(".")
    with pytest.raises(AuthenticationError):
        decode_token(f"{head}.{body}.{sig[:-4]}xxxx", expected_type="access")


def test_credential_encryption_round_trip():
    secret = "EAAG-super-secret-page-token"
    ciphertext = encrypt_secret(secret)
    assert secret not in ciphertext
    assert decrypt_secret(ciphertext) == secret


class TestMetaSignature:
    secret = "meta-app-secret"

    def _sign(self, body: bytes) -> str:
        return "sha256=" + hmac.new(
            self.secret.encode(), body, hashlib.sha256
        ).hexdigest()

    def test_valid_signature_accepted(self):
        body = json.dumps({"object": "whatsapp_business_account"}).encode()
        assert verify_meta_signature(body, self._sign(body), self.secret)

    def test_modified_body_rejected(self):
        body = b'{"object":"page"}'
        signature = self._sign(body)
        assert not verify_meta_signature(b'{"object":"evil"}', signature, self.secret)

    def test_missing_header_rejected(self):
        assert not verify_meta_signature(b"{}", None, self.secret)

    def test_no_secret_configured_rejects_everything(self):
        assert not verify_meta_signature(b"{}", "sha256=deadbeef", "")

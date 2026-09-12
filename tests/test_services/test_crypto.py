"""Tests for app.security.crypto — the AES-256-GCM used for IBANs and bank tokens.

This module had zero coverage despite being the thing standing between a stolen
database file and the account numbers inside it. There was no round-trip test.
"""

import base64

import pytest

from app.security.crypto import decrypt, encrypt


class TestRoundTrip:
    def test_round_trip(self, db):
        assert decrypt(encrypt("NL91ABNA0417164300")) == "NL91ABNA0417164300"

    def test_round_trip_empty_string(self, db):
        assert decrypt(encrypt("")) == ""

    def test_round_trip_unicode(self, db):
        # Dutch merchant names carry accents; a naive latin-1 path would corrupt these.
        value = "Café Zürich — Amsterdam €12,50"
        assert decrypt(encrypt(value)) == value

    def test_round_trip_long_value(self, db):
        value = "x" * 10_000
        assert decrypt(encrypt(value)) == value


class TestCiphertextProperties:
    def test_ciphertext_does_not_contain_plaintext(self, db):
        secret = "NL91ABNA0417164300"
        assert secret not in encrypt(secret)

    def test_same_plaintext_encrypts_differently_each_time(self, db):
        """A fresh 12-byte nonce per call — identical IBANs must not look identical.

        Without this, an attacker reading the database could tell which
        transactions share a counterparty even without breaking the cipher.
        """
        secret = "NL91ABNA0417164300"
        assert encrypt(secret) != encrypt(secret)

    def test_ciphertext_is_urlsafe_base64(self, db):
        token = encrypt("value")
        # Must survive storage in a TEXT column and any URL-ish handling.
        assert base64.urlsafe_b64decode(token.encode())
        assert "+" not in token and "/" not in token


class TestFailurePaths:
    def test_rejects_invalid_base64(self, db):
        with pytest.raises(ValueError, match="Invalid base64"):
            decrypt("not!valid!base64!")

    def test_rejects_token_too_short(self, db):
        # Shorter than nonce(12) + tag(16).
        short = base64.urlsafe_b64encode(b"tiny").decode()
        with pytest.raises(ValueError, match="too short"):
            decrypt(short)

    def test_rejects_tampered_ciphertext(self, db):
        """GCM is authenticated: flipping a byte must fail, not decrypt to garbage."""
        token = encrypt("NL91ABNA0417164300")
        raw = bytearray(base64.urlsafe_b64decode(token.encode()))
        raw[-1] ^= 0x01  # flip one bit of the auth tag
        tampered = base64.urlsafe_b64encode(bytes(raw)).decode()

        with pytest.raises(ValueError, match="decryption failed"):
            decrypt(tampered)

    def test_rejects_wrong_key(self, db, monkeypatch):
        """A token encrypted under a different master key must not decrypt."""
        import app.config as config_module

        token = encrypt("NL91ABNA0417164300")

        rotated = config_module._secrets.model_copy(deep=True)
        rotated.token_encryption.master_key = "c" * 64
        monkeypatch.setattr(config_module, "_secrets", rotated)

        with pytest.raises(ValueError, match="decryption failed"):
            decrypt(token)

"""AES-GCM encrypt/decrypt using the token_encryption.master_key.

The master_key is stored as a 64-character hex string (32 bytes).
Each ciphertext is base64url-encoded as: nonce(12) || tag(16) || ciphertext,
all concatenated and encoded together.
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_secrets


def _get_key() -> bytes:
    """Return the 32-byte AES key decoded from the master_key hex string."""
    master_hex = get_secrets().token_encryption.master_key
    return bytes.fromhex(master_hex)


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* with AES-256-GCM.

    Returns a base64url-encoded string: nonce(12) || ciphertext+tag.
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)
    raw = nonce + ct_with_tag
    return base64.urlsafe_b64encode(raw).decode()


def decrypt(token: str) -> str:
    """Decrypt a value previously encrypted with :func:`encrypt`.

    Raises :class:`ValueError` if the token is malformed or authentication fails.
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode())
    except Exception as exc:
        raise ValueError("Invalid base64 in encrypted token") from exc

    if len(raw) < 12 + 16:
        raise ValueError("Encrypted token is too short")

    nonce = raw[:12]
    ct_with_tag = raw[12:]
    key = _get_key()
    aesgcm = AESGCM(key)
    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ct_with_tag, None)
    except Exception as exc:
        raise ValueError("AES-GCM decryption failed — bad key or corrupted data") from exc

    return plaintext_bytes.decode()

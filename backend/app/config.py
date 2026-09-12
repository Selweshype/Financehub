import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel

if TYPE_CHECKING:
    from fastapi import Request

# Placeholder key material shipped in secrets/secrets.dev.yaml.  Finding M2:
# these are committed to the repository and therefore public.  The app refuses
# to start on them outside development.
_PLACEHOLDER_KEYS = {
    "0000000000000000000000000000000000000000000000000000000000000001",
    "0000000000000000000000000000000000000000000000000000000000000002",
    "dev-secret-key-not-for-production-use-only",
}


def is_development() -> bool:
    """True when FINANCEHUB_ENV explicitly says development."""
    return os.environ.get("FINANCEHUB_ENV", "").strip().lower() == "development"


def get_rp_id(request: "Request") -> str:
    """Return the WebAuthn Relying Party ID.

    Read from FINANCEHUB_RP_ID rather than ``request.url.hostname``: the
    hostname comes from the client-supplied Host header, so deriving the RP ID
    from it lets an attacker who can set that header steer the ceremony to a
    domain they control.  Falling back to the request host is permitted only
    in development, where the app is reached over loopback.
    """
    configured = os.environ.get("FINANCEHUB_RP_ID", "").strip()
    if configured:
        return configured
    if is_development():
        return request.url.hostname or "localhost"
    raise RuntimeError(
        "FINANCEHUB_RP_ID must be set — refusing to derive the WebAuthn RP ID "
        "from the client-supplied Host header."
    )


def get_expected_origin(request: "Request") -> str:
    """Return the origin WebAuthn assertions must have been created for."""
    configured = os.environ.get("FINANCEHUB_ORIGIN", "").strip()
    if configured:
        return configured
    if is_development():
        return f"{request.url.scheme}://{request.url.netloc}"
    raise RuntimeError(
        "FINANCEHUB_ORIGIN must be set — refusing to derive the expected "
        "WebAuthn origin from the client-supplied Host header."
    )


class DatabaseConfig(BaseModel):
    """SQLCipher database encryption key."""

    key: str


class AppConfig(BaseModel):
    """Application-level secrets (session signing key)."""

    secret_key: str


class NordigenConfig(BaseModel):
    """GoCardless Nordigen API credentials."""

    secret_id: str
    secret_key: str


class TokenEncryptionConfig(BaseModel):
    """Master key used to derive AES-GCM keys for stored bank tokens."""

    master_key: str


class ResticConfig(BaseModel):
    """Restic backup repository credentials."""

    password: str
    repository: str


class Secrets(BaseModel):
    """Validated secrets loaded from SOPS-encrypted YAML at startup."""

    database: DatabaseConfig
    app: AppConfig
    nordigen: NordigenConfig
    token_encryption: TokenEncryptionConfig
    restic: ResticConfig


_secrets: Secrets | None = None


def load_secrets() -> Secrets:
    """Load and return a validated Secrets model.

    In dev mode (FINANCEHUB_DEV_SECRETS env var set to a YAML file path),
    the plain YAML file is loaded directly without SOPS.
    In production, the SOPS-encrypted secrets.enc.yaml is decrypted.

    Raises RuntimeError if decryption fails or required secrets are missing.
    Called once during application lifespan startup.
    """
    dev_secrets_path = os.environ.get("FINANCEHUB_DEV_SECRETS")
    if dev_secrets_path:
        # Finding M2: this path bypasses SOPS entirely and the shipped dev file
        # contains committed, publicly-known keys.  Require an explicit
        # development environment so it cannot be switched on by accident in
        # production.
        if not is_development():
            raise RuntimeError(
                "FINANCEHUB_DEV_SECRETS is only honoured when "
                "FINANCEHUB_ENV=development. Refusing to load plaintext secrets."
            )
        p = Path(dev_secrets_path)
        if not p.exists():
            raise RuntimeError(
                f"FINANCEHUB_DEV_SECRETS set but file not found: {dev_secrets_path}"
            )
        with open(p) as f:
            raw = yaml.safe_load(f)
        return Secrets(**raw)

    secrets_path = Path("/secrets/secrets.enc.yaml")
    age_key_path = Path("/secrets/age-key.txt")

    # Fixed argv (no shell, no user-controlled arguments) with an explicit
    # minimal PATH — sops is installed at /usr/local/bin by the Dockerfile.
    result = subprocess.run(  # noqa: S603
        ["sops", "--decrypt", str(secrets_path)],  # noqa: S607
        capture_output=True,
        text=True,
        env={
            "SOPS_AGE_KEY_FILE": str(age_key_path),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        },
        timeout=15,
    )

    if result.returncode != 0:
        raise RuntimeError(f"SOPS decryption failed (exit {result.returncode})")

    raw = yaml.safe_load(result.stdout)
    loaded = Secrets(**raw)
    _reject_placeholder_secrets(loaded)
    return loaded


def _reject_placeholder_secrets(loaded: "Secrets") -> None:
    """Refuse to run production on the committed development key material."""
    if is_development():
        return

    offenders = [
        name
        for name, value in (
            ("database.key", loaded.database.key),
            ("app.secret_key", loaded.app.secret_key),
            ("token_encryption.master_key", loaded.token_encryption.master_key),
        )
        if value in _PLACEHOLDER_KEYS
    ]
    if offenders:
        raise RuntimeError(
            "Refusing to start: these secrets still hold the public placeholder "
            f"values from secrets/secrets.dev.yaml: {', '.join(offenders)}. "
            "Generate real values with: python3 -c \"import secrets; "
            'print(secrets.token_hex(32))"'
        )


def get_secrets() -> Secrets:
    """Return the singleton Secrets instance loaded at startup.

    Raises RuntimeError if called before the application lifespan has run.
    """
    if _secrets is None:
        raise RuntimeError("Secrets not initialized — app not started via lifespan")
    return _secrets

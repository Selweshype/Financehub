import os
import subprocess
import yaml
from pathlib import Path
from pydantic import BaseModel


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

    result = subprocess.run(
        ["sops", "--decrypt", str(secrets_path)],
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
    return Secrets(**raw)


def get_secrets() -> Secrets:
    """Return the singleton Secrets instance loaded at startup.

    Raises RuntimeError if called before the application lifespan has run.
    """
    if _secrets is None:
        raise RuntimeError("Secrets not initialized — app not started via lifespan")
    return _secrets

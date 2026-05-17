import subprocess
import yaml
from pathlib import Path
from pydantic import BaseModel


class DatabaseConfig(BaseModel):
    key: str


class AppConfig(BaseModel):
    secret_key: str


class NordigenConfig(BaseModel):
    secret_id: str
    secret_key: str


class TokenEncryptionConfig(BaseModel):
    master_key: str


class ResticConfig(BaseModel):
    password: str
    repository: str


class Secrets(BaseModel):
    database: DatabaseConfig
    app: AppConfig
    nordigen: NordigenConfig
    token_encryption: TokenEncryptionConfig
    restic: ResticConfig


_secrets: Secrets | None = None


def load_secrets() -> Secrets:
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
    if _secrets is None:
        raise RuntimeError("Secrets not initialized — app not started via lifespan")
    return _secrets

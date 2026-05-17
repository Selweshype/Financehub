"""Tests for backend/app/config.py — secrets loading and Pydantic models."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
import yaml
from pydantic import ValidationError

import app.config as config_module
from app.config import (
    AppConfig,
    DatabaseConfig,
    NordigenConfig,
    ResticConfig,
    Secrets,
    TokenEncryptionConfig,
    get_secrets,
    load_secrets,
)


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


class TestDatabaseConfig:
    def test_valid(self):
        cfg = DatabaseConfig(key="abc123")
        assert cfg.key == "abc123"

    def test_missing_key_raises(self):
        with pytest.raises(ValidationError):
            DatabaseConfig()

    def test_key_must_be_string(self):
        # Pydantic coerces ints to str in lax mode but validates type presence
        cfg = DatabaseConfig(key=42)
        assert cfg.key == "42"


class TestAppConfig:
    def test_valid(self):
        cfg = AppConfig(secret_key="supersecret")
        assert cfg.secret_key == "supersecret"

    def test_missing_secret_key_raises(self):
        with pytest.raises(ValidationError):
            AppConfig()


class TestNordigenConfig:
    def test_valid(self):
        cfg = NordigenConfig(secret_id="id1", secret_key="key1")
        assert cfg.secret_id == "id1"
        assert cfg.secret_key == "key1"

    def test_missing_fields_raise(self):
        with pytest.raises(ValidationError):
            NordigenConfig(secret_id="id1")

    def test_both_missing_raises(self):
        with pytest.raises(ValidationError):
            NordigenConfig()


class TestTokenEncryptionConfig:
    def test_valid(self):
        cfg = TokenEncryptionConfig(master_key="masterkey")
        assert cfg.master_key == "masterkey"

    def test_missing_master_key_raises(self):
        with pytest.raises(ValidationError):
            TokenEncryptionConfig()


class TestResticConfig:
    def test_valid(self):
        cfg = ResticConfig(password="pw", repository="s3://bucket/path")
        assert cfg.password == "pw"
        assert cfg.repository == "s3://bucket/path"

    def test_missing_password_raises(self):
        with pytest.raises(ValidationError):
            ResticConfig(repository="s3://bucket/path")

    def test_missing_repository_raises(self):
        with pytest.raises(ValidationError):
            ResticConfig(password="pw")


class TestSecrets:
    def _valid_raw(self):
        return {
            "database": {"key": "dbkey"},
            "app": {"secret_key": "appsecret"},
            "nordigen": {"secret_id": "nid", "secret_key": "nkey"},
            "token_encryption": {"master_key": "mkey"},
            "restic": {"password": "rpw", "repository": "s3://bucket/path"},
        }

    def test_valid_construction(self):
        raw = self._valid_raw()
        s = Secrets(**raw)
        assert s.database.key == "dbkey"
        assert s.app.secret_key == "appsecret"
        assert s.nordigen.secret_id == "nid"
        assert s.nordigen.secret_key == "nkey"
        assert s.token_encryption.master_key == "mkey"
        assert s.restic.password == "rpw"
        assert s.restic.repository == "s3://bucket/path"

    def test_missing_section_raises(self):
        raw = self._valid_raw()
        del raw["database"]
        with pytest.raises(ValidationError):
            Secrets(**raw)

    def test_nested_missing_field_raises(self):
        raw = self._valid_raw()
        raw["database"] = {}  # missing 'key'
        with pytest.raises(ValidationError):
            Secrets(**raw)

    def test_all_sections_required(self):
        for section in ("database", "app", "nordigen", "token_encryption", "restic"):
            raw = self._valid_raw()
            del raw[section]
            with pytest.raises(ValidationError):
                Secrets(**raw)


# ---------------------------------------------------------------------------
# load_secrets() tests
# ---------------------------------------------------------------------------


def _make_valid_yaml() -> str:
    data = {
        "database": {"key": "dbkey"},
        "app": {"secret_key": "appsecret"},
        "nordigen": {"secret_id": "nid", "secret_key": "nkey"},
        "token_encryption": {"master_key": "mkey"},
        "restic": {"password": "rpw", "repository": "s3://bucket/path"},
    }
    return yaml.dump(data)


class TestLoadSecrets:
    def test_success(self):
        """load_secrets returns a Secrets instance when sops succeeds."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = _make_valid_yaml()

        with patch("app.config.subprocess.run", return_value=mock_result) as mock_run:
            result = load_secrets()

        assert isinstance(result, Secrets)
        assert result.database.key == "dbkey"
        assert result.app.secret_key == "appsecret"
        assert result.nordigen.secret_id == "nid"
        assert result.restic.repository == "s3://bucket/path"

        # Verify the subprocess was called with correct sops arguments
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "sops"
        assert "--decrypt" in cmd
        assert "/secrets/secrets.enc.yaml" in cmd

    def test_sops_env_contains_age_key_file(self):
        """load_secrets passes SOPS_AGE_KEY_FILE in environment."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = _make_valid_yaml()

        with patch("app.config.subprocess.run", return_value=mock_result) as mock_run:
            load_secrets()

        env = mock_run.call_args[1]["env"]
        assert "SOPS_AGE_KEY_FILE" in env
        assert env["SOPS_AGE_KEY_FILE"] == "/secrets/age-key.txt"

    def test_sops_timeout_is_set(self):
        """load_secrets enforces a 15-second timeout on sops subprocess."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = _make_valid_yaml()

        with patch("app.config.subprocess.run", return_value=mock_result) as mock_run:
            load_secrets()

        assert mock_run.call_args[1]["timeout"] == 15

    def test_nonzero_returncode_raises_runtime_error(self):
        """load_secrets raises RuntimeError when sops exits non-zero."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("app.config.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="SOPS decryption failed"):
                load_secrets()

    def test_error_message_includes_exit_code(self):
        """RuntimeError message includes the exit code from sops."""
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stdout = ""

        with patch("app.config.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="exit 2"):
                load_secrets()

    def test_invalid_yaml_from_sops_raises(self):
        """load_secrets raises if sops output is not valid YAML mapping."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "this is not yaml: [{"

        with patch("app.config.subprocess.run", return_value=mock_result):
            with pytest.raises(Exception):
                load_secrets()

    def test_yaml_missing_required_section_raises_validation_error(self):
        """load_secrets raises ValidationError if decrypted YAML is missing sections."""
        incomplete = yaml.dump({"database": {"key": "only_this"}})
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = incomplete

        with patch("app.config.subprocess.run", return_value=mock_result):
            with pytest.raises(ValidationError):
                load_secrets()

    def test_capture_output_and_text_are_set(self):
        """load_secrets calls subprocess.run with capture_output=True, text=True."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = _make_valid_yaml()

        with patch("app.config.subprocess.run", return_value=mock_result) as mock_run:
            load_secrets()

        kwargs = mock_run.call_args[1]
        assert kwargs.get("capture_output") is True
        assert kwargs.get("text") is True


# ---------------------------------------------------------------------------
# get_secrets() tests
# ---------------------------------------------------------------------------


class TestGetSecrets:
    def setup_method(self):
        """Reset module-level _secrets before each test."""
        config_module._secrets = None

    def teardown_method(self):
        """Clean up after each test."""
        config_module._secrets = None

    def test_raises_when_not_initialized(self):
        """get_secrets raises RuntimeError if _secrets is None."""
        config_module._secrets = None
        with pytest.raises(RuntimeError, match="Secrets not initialized"):
            get_secrets()

    def test_returns_secrets_when_initialized(self):
        """get_secrets returns the _secrets instance when it has been set."""
        raw = {
            "database": {"key": "dbkey"},
            "app": {"secret_key": "appsecret"},
            "nordigen": {"secret_id": "nid", "secret_key": "nkey"},
            "token_encryption": {"master_key": "mkey"},
            "restic": {"password": "rpw", "repository": "s3://bucket/path"},
        }
        fake_secrets = Secrets(**raw)
        config_module._secrets = fake_secrets

        result = get_secrets()
        assert result is fake_secrets

    def test_error_message_mentions_lifespan(self):
        """RuntimeError from get_secrets mentions lifespan to help debugging."""
        config_module._secrets = None
        with pytest.raises(RuntimeError, match="lifespan"):
            get_secrets()

    def test_returns_same_instance(self):
        """get_secrets returns the exact same object (no copy)."""
        raw = {
            "database": {"key": "k"},
            "app": {"secret_key": "s"},
            "nordigen": {"secret_id": "i", "secret_key": "k2"},
            "token_encryption": {"master_key": "m"},
            "restic": {"password": "p", "repository": "r"},
        }
        fake_secrets = Secrets(**raw)
        config_module._secrets = fake_secrets

        assert get_secrets() is fake_secrets
        assert get_secrets() is fake_secrets  # stable across multiple calls

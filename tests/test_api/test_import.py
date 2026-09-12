"""HTTP-level tests for the CSV import route.

Covers the parts the service-level tests cannot: the auth guard, multipart
upload handling, and that a bad file produces a rendered error rather than a 500.
"""

import time

import pytest
from fastapi.testclient import TestClient

import app.config as config_module
from app.config import (
    AppConfig,
    DatabaseConfig,
    NordigenConfig,
    ResticConfig,
    Secrets,
    TokenEncryptionConfig,
)

TEST_DB_KEY = "a" * 64
TEST_MASTER_KEY = "b" * 64

ING_CSV = (
    '"Datum","Naam / Omschrijving","Rekening","Tegenrekening","Code","Af Bij",'
    '"Bedrag (EUR)","Mutatiesoort","Mededelingen"\r\n'
    '"20260304","Albert Heijn 1234","NL01INGB0001234567","","BA","Af",'
    '"25,50","Betaalautomaat","Pasvolgnr 001"\r\n'
).encode()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.database import Base, init_db
    from app.security import bootstrap, challenge, ratelimit
    from app.services.categorizer import invalidate_cache

    db_path = str(tmp_path / "api.db")
    monkeypatch.setenv("FINANCEHUB_DB_KEY", TEST_DB_KEY)
    monkeypatch.setenv("FINANCEHUB_ENV", "development")
    monkeypatch.setenv("FINANCEHUB_RP_ID", "testserver")
    monkeypatch.setenv("FINANCEHUB_ORIGIN", "http://testserver")

    config_module._secrets = Secrets(
        database=DatabaseConfig(key=TEST_DB_KEY),
        app=AppConfig(secret_key="test-app-secret"),
        nordigen=NordigenConfig(secret_id="nid", secret_key="nkey"),
        token_encryption=TokenEncryptionConfig(master_key=TEST_MASTER_KEY),
        restic=ResticConfig(password="rpw", repository="s3://bucket/path"),
    )

    init_db(TEST_DB_KEY, db_path)

    import app.database as db_module
    import app.models.accounts  # noqa: F401
    import app.models.alerts  # noqa: F401
    import app.models.auth  # noqa: F401
    import app.models.budgets  # noqa: F401
    import app.models.categories  # noqa: F401
    import app.models.goals  # noqa: F401
    import app.models.liabilities  # noqa: F401
    import app.models.nordigen  # noqa: F401
    import app.models.snapshots  # noqa: F401
    import app.models.transactions  # noqa: F401

    Base.metadata.create_all(db_module._app_engine)

    challenge.clear()
    ratelimit.clear()
    bootstrap.clear_bootstrap_token()
    invalidate_cache()

    from app.main import app as fastapi_app

    yield TestClient(fastapi_app)

    challenge.clear()
    ratelimit.clear()
    bootstrap.clear_bootstrap_token()
    invalidate_cache()
    config_module._secrets = None


@pytest.fixture()
def authed_client(client):
    """A client carrying a valid session cookie."""
    from app.database import get_db
    from app.models.auth import UserSession
    from app.security.session import SESSION_TTL, _hash_token, cookie_name

    token = "test-session-token"
    now = int(time.time())

    db = next(get_db())
    db.add(
        UserSession(
            token_hash=_hash_token(token),
            auth_method="totp",
            created_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_TTL,
        )
    )
    db.commit()
    db.close()

    client.cookies.set(cookie_name(), token)
    return client


class TestAuthGuard:
    def test_import_form_requires_a_session(self, client):
        resp = client.get("/transactions/import", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/auth/login"

    def test_import_upload_requires_a_session(self, client):
        resp = client.post(
            "/transactions/import",
            files={"file": ("x.csv", ING_CSV, "text/csv")},
            follow_redirects=False,
        )
        assert resp.status_code == 307


class TestImportForm:
    def test_renders(self, authed_client):
        resp = authed_client.get("/transactions/import")
        assert resp.status_code == 200
        assert "Import transactions" in resp.text


class TestImportUpload:
    def test_successful_upload_reports_counts(self, authed_client):
        resp = authed_client.post(
            "/transactions/import",
            files={"file": ("ing.csv", ING_CSV, "text/csv")},
            data={"account_label": "ING Betaalrekening"},
        )

        assert resp.status_code == 200
        assert "ING import complete" in resp.text

        from app.database import get_db
        from app.models.transactions import Transaction

        db = next(get_db())
        try:
            assert db.query(Transaction).count() == 1
        finally:
            db.close()

    def test_reimport_reports_duplicates_and_inserts_nothing(self, authed_client):
        files = {"file": ("ing.csv", ING_CSV, "text/csv")}
        authed_client.post("/transactions/import", files=files)
        authed_client.post(
            "/transactions/import", files={"file": ("ing.csv", ING_CSV, "text/csv")}
        )

        from app.database import get_db
        from app.models.transactions import Transaction

        db = next(get_db())
        try:
            assert db.query(Transaction).count() == 1
        finally:
            db.close()

    def test_non_csv_is_rejected(self, authed_client):
        resp = authed_client.post(
            "/transactions/import",
            files={"file": ("statement.pdf", b"%PDF-1.4", "application/pdf")},
        )
        assert resp.status_code == 200
        assert ".csv file" in resp.text

    def test_unknown_layout_renders_an_error_not_a_500(self, authed_client):
        """A wrong-format file must be reported, never guessed at or crashed on."""
        other_bank = b'"Transaction Date","Debit","Credit"\r\n"2026-03-04","10.00",""\r\n'
        resp = authed_client.post(
            "/transactions/import",
            files={"file": ("other.csv", other_bank, "text/csv")},
        )

        assert resp.status_code == 200
        assert "Unrecognised CSV format" in resp.text

    def test_cross_site_upload_is_blocked(self, authed_client):
        """The CSRF middleware must cover the upload route too."""
        resp = authed_client.post(
            "/transactions/import",
            files={"file": ("ing.csv", ING_CSV, "text/csv")},
            headers={"Origin": "https://evil.example.com"},
        )
        assert resp.status_code == 403

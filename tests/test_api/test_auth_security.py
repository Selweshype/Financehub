"""Regression tests for the authentication security fixes.

Each test pins one finding from the security audit.  They are written to fail
loudly if the corresponding protection is ever removed.
"""

import os
import time
from unittest.mock import patch

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


def _fake_secrets() -> Secrets:
    return Secrets(
        database=DatabaseConfig(key=TEST_DB_KEY),
        app=AppConfig(secret_key="test-app-secret"),
        nordigen=NordigenConfig(secret_id="nid", secret_key="nkey"),
        token_encryption=TokenEncryptionConfig(master_key=TEST_MASTER_KEY),
        restic=ResticConfig(password="rpw", repository="s3://bucket/path"),
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient backed by a real, throwaway SQLCipher database."""
    from app.database import Base, init_db
    from app.security import bootstrap, challenge, ratelimit

    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("FINANCEHUB_DB_KEY", TEST_DB_KEY)
    monkeypatch.setenv("FINANCEHUB_DB_PATH", db_path)
    monkeypatch.setenv("FINANCEHUB_ENV", "development")
    monkeypatch.setenv("FINANCEHUB_RP_ID", "testserver")
    monkeypatch.setenv("FINANCEHUB_ORIGIN", "http://testserver")

    secrets_obj = _fake_secrets()
    config_module._secrets = secrets_obj

    init_db(TEST_DB_KEY, db_path)

    import app.database as db_module
    import app.models.accounts  # noqa: F401 - register tables
    import app.models.auth  # noqa: F401
    import app.models.budgets  # noqa: F401
    import app.models.categories  # noqa: F401
    import app.models.goals  # noqa: F401
    import app.models.liabilities  # noqa: F401
    import app.models.nordigen  # noqa: F401
    import app.models.snapshots  # noqa: F401
    import app.models.transactions  # noqa: F401
    import app.models.alerts  # noqa: F401

    Base.metadata.create_all(db_module._app_engine)

    challenge.clear()
    ratelimit.clear()
    bootstrap.clear_bootstrap_token()

    from app.main import app as fastapi_app

    # Bypass lifespan (it would try to load real secrets / start the scheduler).
    with TestClient(fastapi_app) as c:
        yield c

    challenge.clear()
    ratelimit.clear()
    bootstrap.clear_bootstrap_token()
    config_module._secrets = None


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """Same as `client` but without entering lifespan (no scheduler)."""
    yield from _build_client(tmp_path, monkeypatch)


def _build_client(tmp_path, monkeypatch):
    from app.database import Base, init_db
    from app.security import bootstrap, challenge, ratelimit

    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("FINANCEHUB_DB_KEY", TEST_DB_KEY)
    monkeypatch.setenv("FINANCEHUB_ENV", "development")
    monkeypatch.setenv("FINANCEHUB_RP_ID", "testserver")
    monkeypatch.setenv("FINANCEHUB_ORIGIN", "http://testserver")
    config_module._secrets = _fake_secrets()

    init_db(TEST_DB_KEY, db_path)

    import app.database as db_module
    import app.models.alerts  # noqa: F401
    import app.models.accounts  # noqa: F401
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

    from app.main import app as fastapi_app

    yield TestClient(fastapi_app)

    challenge.clear()
    ratelimit.clear()
    bootstrap.clear_bootstrap_token()
    config_module._secrets = None


# ---------------------------------------------------------------------------
# C1 — WebAuthn authentication bypass
# ---------------------------------------------------------------------------


def test_webauthn_complete_rejects_unverified_credential(app_client):
    """Finding C1: posting a known credential id must NOT create a session.

    The old stub looked the credential up and issued a 30-day cookie. Now the
    assertion has to verify cryptographically first.
    """
    from app.database import get_db
    from app.models.auth import WebAuthnCredential

    db = next(get_db())
    db.add(
        WebAuthnCredential(
            credential_id="known-credential-id",
            public_key="AAAA",
            sign_count=0,
            created_at=int(time.time()),
        )
    )
    db.commit()
    db.close()

    # Obtain a legitimate challenge first, so the only thing missing is the
    # signature — this is precisely the old bypass.
    begin = app_client.get("/auth/webauthn/authenticate/begin")
    assert begin.status_code == 200
    challenge_id = begin.json()["challenge_id"]

    resp = app_client.post(
        "/auth/webauthn/authenticate/complete",
        json={
            "challenge_id": challenge_id,
            "credential": {
                "id": "known-credential-id",
                "rawId": "known-credential-id",
                "type": "public-key",
                "response": {
                    "authenticatorData": "AAAA",
                    "clientDataJSON": "AAAA",
                    "signature": "AAAA",
                    "userHandle": None,
                },
            },
        },
    )

    assert resp.status_code == 401
    assert "__Host-fh" not in resp.cookies
    assert "fh_session" not in resp.cookies


def test_authenticate_begin_does_not_enumerate_credentials(app_client):
    """Finding L2: credential ids must not be handed to anonymous callers."""
    from app.database import get_db
    from app.models.auth import WebAuthnCredential

    db = next(get_db())
    db.add(
        WebAuthnCredential(
            credential_id="secret-credential-id",
            public_key="AAAA",
            sign_count=0,
            created_at=int(time.time()),
        )
    )
    db.commit()
    db.close()

    resp = app_client.get("/auth/webauthn/authenticate/begin")
    assert resp.status_code == 200
    assert "secret-credential-id" not in resp.text


# ---------------------------------------------------------------------------
# C2 / C3 — unauthenticated enrollment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/auth/webauthn/register/begin"),
        ("post", "/auth/webauthn/register/complete"),
        ("get", "/auth/totp/setup"),
        ("post", "/auth/totp/activate"),
    ],
)
def test_enrollment_requires_session_or_setup_token(app_client, method, path):
    """Findings C2 and C3: enrollment was wide open to the internet."""
    from app.security import bootstrap

    bootstrap.clear_bootstrap_token()  # no first-run window open

    resp = getattr(app_client, method)(path, follow_redirects=False)
    assert resp.status_code == 403, f"{method.upper()} {path} was not gated"


def test_enrollment_allowed_with_bootstrap_token(app_client):
    """The first-run setup token opens enrollment exactly once."""
    from app.database import get_db
    from app.security import bootstrap

    db = next(get_db())
    token = bootstrap.init_bootstrap_token(db)
    db.close()
    assert token, "a setup token should be minted when no credential exists"

    ok = app_client.get(f"/auth/totp/setup?token={token}")
    assert ok.status_code == 200

    bad = app_client.get("/auth/totp/setup?token=wrong-token")
    assert bad.status_code == 403


def test_totp_activate_rejects_wrong_code(app_client):
    """A bad confirmation code must not install a new TOTP secret."""
    import pyotp

    from app.database import get_db
    from app.models.auth import TotpSecret
    from app.security import bootstrap

    db = next(get_db())
    token = bootstrap.init_bootstrap_token(db)
    db.close()

    secret = pyotp.random_base32()
    resp = app_client.post(
        f"/auth/totp/activate?token={token}",
        data={"secret": secret, "code": "000000"},
        follow_redirects=False,
    )
    assert resp.status_code == 400

    db = next(get_db())
    assert db.query(TotpSecret).count() == 0
    db.close()


# ---------------------------------------------------------------------------
# C4 — challenge replay
# ---------------------------------------------------------------------------


def test_challenge_is_single_use(app_client):
    """Finding C4: a challenge must never be redeemable twice."""
    from app.security import challenge

    challenge_id, value = challenge.issue("authentication")
    assert challenge.consume(challenge_id, "authentication") == value
    assert challenge.consume(challenge_id, "authentication") is None


def test_challenge_is_purpose_bound(app_client):
    """A registration challenge must not satisfy the authentication ceremony."""
    from app.security import challenge

    challenge_id, _ = challenge.issue("registration")
    assert challenge.consume(challenge_id, "authentication") is None


def test_webauthn_complete_rejects_replayed_challenge(app_client):
    """An unknown or already-consumed challenge id is refused before any lookup."""
    resp = app_client.post(
        "/auth/webauthn/authenticate/complete",
        json={
            "challenge_id": "never-issued",
            "credential": {"id": "x", "type": "public-key", "response": {}},
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# H1 — rate limiting
# ---------------------------------------------------------------------------


def test_totp_verify_is_rate_limited(app_client):
    """Finding H1: a six-digit code is brute-forceable without a throttle."""
    codes = [
        app_client.post("/auth/totp/verify", data={"code": "000000"}).status_code
        for _ in range(7)
    ]
    assert 429 in codes, f"no lockout after 7 attempts: {codes}"


def test_rate_limit_sets_retry_after(app_client):
    from app.security import ratelimit

    last = None
    for _ in range(8):
        last = app_client.post("/auth/totp/verify", data={"code": "000000"})
    assert last.status_code == 429
    assert "Retry-After" in last.headers
    ratelimit.clear()


# ---------------------------------------------------------------------------
# H2 — CSRF
# ---------------------------------------------------------------------------


def test_cross_site_post_is_blocked(app_client):
    """Finding H2: nothing rejected cross-site state-changing requests."""
    resp = app_client.post(
        "/auth/logout",
        headers={"Origin": "https://evil.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_sec_fetch_site_cross_site_is_blocked(app_client):
    resp = app_client.post(
        "/auth/logout",
        headers={"Sec-Fetch-Site": "cross-site"},
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_same_origin_post_is_allowed(app_client):
    """The CSRF check must not break legitimate same-origin form posts."""
    resp = app_client.post(
        "/auth/logout",
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
        follow_redirects=False,
    )
    assert resp.status_code != 403


# ---------------------------------------------------------------------------
# H5 / M2 — key and secret validation
# ---------------------------------------------------------------------------


def test_non_hex_db_key_is_rejected():
    """Finding H5: a key with a quote must never reach the PRAGMA statement."""
    from app.database import _apply_pragmas

    class FakeConn:
        def __init__(self):
            self.statements = []

        def execute(self, sql):
            self.statements.append(sql)

    conn = FakeConn()
    with patch.dict(os.environ, {"FINANCEHUB_DB_KEY": "abc' OR 1=1--"}):
        with pytest.raises(ValueError):
            _apply_pragmas(conn, None)

    assert conn.statements == [], "no SQL should run with an invalid key"


def test_dev_secrets_bypass_requires_development_env(tmp_path):
    """Finding M2: the SOPS bypass must not be usable in production."""
    dev_file = tmp_path / "dev.yaml"
    dev_file.write_text("database:\n  key: x\n")

    env = {
        "FINANCEHUB_DEV_SECRETS": str(dev_file),
        "FINANCEHUB_ENV": "production",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(RuntimeError, match="FINANCEHUB_ENV=development"):
            config_module.load_secrets()


def test_placeholder_secrets_rejected_outside_development():
    """The committed dev key material must not boot a production instance."""
    placeholder = Secrets(
        database=DatabaseConfig(key="0" * 63 + "1"),
        app=AppConfig(secret_key="dev-secret-key-not-for-production-use-only"),
        nordigen=NordigenConfig(secret_id="a", secret_key="b"),
        token_encryption=TokenEncryptionConfig(master_key="0" * 63 + "2"),
        restic=ResticConfig(password="p", repository="r"),
    )
    with patch.dict(os.environ, {"FINANCEHUB_ENV": "production"}, clear=False):
        with pytest.raises(RuntimeError, match="placeholder"):
            config_module._reject_placeholder_secrets(placeholder)


# ---------------------------------------------------------------------------
# M4 / L1 — response headers
# ---------------------------------------------------------------------------


def test_csp_permits_inline_style_attributes(app_client):
    """Finding M4: without style-src-attr the whole UI renders unstyled."""
    resp = app_client.get("/auth/login")
    csp = resp.headers["Content-Security-Policy"]
    assert "style-src-attr 'unsafe-inline'" in csp
    assert "object-src 'none'" in csp
    # script-src must stay strict — nonce only, no unsafe-inline.
    script_src = [p for p in csp.split(";") if p.strip().startswith("script-src")][0]
    assert "unsafe-inline" not in script_src


def test_security_headers_present_on_dev_path(app_client):
    """Finding L1: these were only set by the production Caddyfile."""
    resp = app_client.get("/auth/login")
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in resp.headers
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


# ---------------------------------------------------------------------------
# M1 — session lifecycle
# ---------------------------------------------------------------------------


def test_expired_sessions_are_purged(app_client):
    """Finding M1: expired rows were never deleted."""
    from app.database import get_db
    from app.models.auth import UserSession
    from app.security.session import purge_expired_sessions

    db = next(get_db())
    now = int(time.time())
    db.add(
        UserSession(
            token_hash="expired-hash",
            auth_method="totp",
            created_at=now - 10_000,
            last_seen_at=now - 10_000,
            expires_at=now - 1,
        )
    )
    db.add(
        UserSession(
            token_hash="live-hash",
            auth_method="totp",
            created_at=now,
            last_seen_at=now,
            expires_at=now + 10_000,
        )
    )
    db.commit()

    removed = purge_expired_sessions(db)
    assert removed == 1
    remaining = [s.token_hash for s in db.query(UserSession).all()]
    assert remaining == ["live-hash"]
    db.close()


def test_idle_session_is_rejected(app_client):
    """A session untouched past the idle window must stop authenticating."""
    from app.database import get_db
    from app.models.auth import UserSession
    from app.security.session import (
        SESSION_IDLE_TTL,
        _hash_token,
        cookie_name,
        get_optional_session,
    )

    db = next(get_db())
    now = int(time.time())
    token = "idle-token-value"
    db.add(
        UserSession(
            token_hash=_hash_token(token),
            auth_method="totp",
            created_at=now - SESSION_IDLE_TTL - 100,
            last_seen_at=now - SESSION_IDLE_TTL - 100,
            expires_at=now + 10_000,  # absolute expiry still in the future
        )
    )
    db.commit()

    class FakeRequest:
        cookies = {cookie_name(): token}

    assert get_optional_session(FakeRequest(), db) is None
    db.close()


# ---------------------------------------------------------------------------
# M5 — Nordigen token expiry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_token_returns_absolute_timestamps():
    """Finding M5: mixed relative/absolute values made tokens look fresh forever."""
    from app.services.nordigen_client import NordigenClient

    client = NordigenClient(secret_id="x", secret_key="y")
    now = int(time.time())
    try:
        result = await client.ensure_token(
            access_token="live-token",
            access_expires_at=now + 3600,
            refresh_token="refresh",
            refresh_expires_at=now + 86400,
        )
        assert result["access_expires_at"] == now + 3600
        assert result["refresh_expires_at"] == now + 86400
        # The old keys must be gone so a stale caller fails loudly, not silently.
        assert "access_expires" not in result
    finally:
        await client.aclose()

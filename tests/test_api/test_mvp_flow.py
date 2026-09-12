"""End-to-end MVP acceptance test.

Walks the whole path a new user takes, against a database built by the real
Alembic migrations (so the seeded categories and Dutch merchant rules are the
genuine ones, not test fixtures):

    first-run setup token -> TOTP enrollment -> login
    -> import a bank CSV -> transactions auto-categorized
    -> set a budget -> spend-vs-budget reflects the imported data
    -> log out -> everything guarded again

This replaces the throwaway script used to verify the security work, which was
never committed and so never ran again.
"""

import subprocess
import time
from decimal import Decimal
from pathlib import Path

import pyotp
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

BACKEND = Path(__file__).resolve().parents[2] / "backend"
TEST_DB_KEY = "a" * 64
TEST_MASTER_KEY = "b" * 64

# One month of a plausible ING export: salary in, groceries out.
ING_CSV = (
    '"Datum","Naam / Omschrijving","Rekening","Tegenrekening","Code","Af Bij",'
    '"Bedrag (EUR)","Mutatiesoort","Mededelingen"\r\n'
    '"20260305","Salaris Werkgever BV","NL01INGB0001234567","NL99BANK0000000001","OV","Bij",'
    '"2.500,00","Overschrijving","Salaris maart"\r\n'
    '"20260306","Albert Heijn 1234","NL01INGB0001234567","","BA","Af",'
    '"25,50","Betaalautomaat","Pasvolgnr 001"\r\n'
    '"20260312","Albert Heijn 5678","NL01INGB0001234567","","BA","Af",'
    '"42,10","Betaalautomaat","Pasvolgnr 002"\r\n'
    '"20260318","Jumbo Amsterdam","NL01INGB0001234567","","BA","Af",'
    '"18,40","Betaalautomaat","Pasvolgnr 003"\r\n'
).encode()

# 25.50 + 42.10 + 18.40
EXPECTED_GROCERY_SPEND = Decimal("86.00")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient over a database built by the real migrations."""
    if not (BACKEND / ".venv" / "bin" / "python").exists():
        pytest.skip("backend virtualenv not present")

    db_path = tmp_path / "mvp.db"
    migrate = subprocess.run(
        [str(BACKEND / ".venv" / "bin" / "python"), "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "FINANCEHUB_DB_KEY": TEST_DB_KEY,
            "FINANCEHUB_DB_PATH": str(db_path),
            "FINANCEHUB_ENV": "development",
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    if migrate.returncode != 0:
        pytest.fail(f"migrations failed:\n{migrate.stdout}\n{migrate.stderr}")

    monkeypatch.setenv("FINANCEHUB_DB_KEY", TEST_DB_KEY)
    monkeypatch.setenv("FINANCEHUB_ENV", "development")
    monkeypatch.setenv("FINANCEHUB_RP_ID", "testserver")
    monkeypatch.setenv("FINANCEHUB_ORIGIN", "http://testserver")
    # Mirrors the local-dev deployment this MVP targets. Without it the session
    # cookie keeps the __Host- prefix and Secure attribute, which no client will
    # store over plain http:// — the login would appear to succeed and every
    # later page assertion would silently run against the login page instead.
    monkeypatch.setenv("FINANCEHUB_INSECURE_COOKIES", "1")

    config_module._secrets = Secrets(
        database=DatabaseConfig(key=TEST_DB_KEY),
        app=AppConfig(secret_key="test-app-secret"),
        nordigen=NordigenConfig(secret_id="nid", secret_key="nkey"),
        token_encryption=TokenEncryptionConfig(master_key=TEST_MASTER_KEY),
        restic=ResticConfig(password="rpw", repository="s3://bucket/path"),
    )

    from app.database import init_db
    from app.security import bootstrap, challenge, ratelimit
    from app.services.categorizer import invalidate_cache

    init_db(TEST_DB_KEY, str(db_path))
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


def _enroll_and_login(client) -> str:
    """First-run enrollment, then a fresh login. Returns the TOTP secret."""
    import re

    from app.database import get_db
    from app.security import bootstrap

    db = next(get_db())
    try:
        token = bootstrap.init_bootstrap_token(db)
    finally:
        db.close()
    assert token, "a first-run setup token should be minted on an empty database"

    page = client.get(f"/auth/totp/setup?token={token}")
    assert page.status_code == 200
    secret = re.search(r'name="secret" value="([A-Z2-7]+)"', page.text).group(1)

    activated = client.post(
        f"/auth/totp/activate?token={token}",
        data={"secret": secret, "code": pyotp.TOTP(secret).now()},
        follow_redirects=False,
    )
    assert activated.status_code == 303

    # Start from a clean slate and log in the way a returning user would.
    client.cookies.clear()
    login = client.post(
        "/auth/totp/verify",
        data={"code": pyotp.TOTP(secret).now()},
        follow_redirects=False,
    )
    assert login.status_code == 303
    return secret


class TestMvpHappyPath:
    def test_full_flow(self, client):
        _enroll_and_login(client)

        # --- every core page renders once authenticated ---------------------
        # follow_redirects=False matters: with it on, an unauthenticated 307 to
        # the login page also returns 200 and the assertion passes vacuously.
        for path in ("/", "/accounts/", "/transactions/", "/categories/", "/budgets/"):
            resp = client.get(path, follow_redirects=False)
            assert resp.status_code == 200, f"{path} returned {resp.status_code}, not 200"

        # --- transactions start empty, and say how to fix that --------------
        empty = client.get("/transactions/")
        assert "No transactions found." in empty.text
        assert "/transactions/import" in empty.text

        # --- import a bank export -------------------------------------------
        imported = client.post(
            "/transactions/import",
            files={"file": ("ing.csv", ING_CSV, "text/csv")},
            data={"account_label": "ING Betaalrekening"},
        )
        assert imported.status_code == 200
        assert "ING import complete" in imported.text

        from app.database import get_db
        from app.models.categories import Category
        from app.models.transactions import Transaction

        db = next(get_db())
        try:
            assert db.query(Transaction).count() == 4

            # The seeded Dutch merchant rules should have caught the groceries.
            groceries = db.query(Category).filter(Category.name == "Groceries").one()
            grocery_txs = (
                db.query(Transaction)
                .filter(Transaction.category_id == groceries.id)
                .all()
            )
            assert len(grocery_txs) == 3, "Albert Heijn x2 and Jumbo should auto-categorize"
            assert all(t.categorization_source == "rule" for t in grocery_txs)

            # Signs survived the Af/Bij mapping.
            assert all(Decimal(t.amount) < 0 for t in grocery_txs)
            salary = (
                db.query(Transaction)
                .filter(Transaction.booking_date == "2026-03-05")
                .one()
            )
            assert Decimal(salary.amount) == Decimal("2500.00")

            groceries_id = groceries.id
            groceries_ext_id = groceries.external_id
        finally:
            db.close()

        # --- the imported rows are visible in the UI ------------------------
        listing = client.get("/transactions/?month=2026-03")
        assert listing.status_code == 200
        assert "Albert Heijn" in listing.text

        # --- the money maths matches a hand calculation ---------------------
        from app.services.budget_service import compute_monthly_spend

        db = next(get_db())
        try:
            spend = compute_monthly_spend(db, "2026-03")
            assert spend[groceries_id] == EXPECTED_GROCERY_SPEND
        finally:
            db.close()

        # --- set a budget and see it reflect the imported spend -------------
        created = client.post(
            "/budgets/",
            data={
                "category_ext_id": groceries_ext_id,
                "monthly_amount": "100.00",
                "rollover_enabled": 0,
            },
        )
        assert created.status_code == 200

        from app.services.budget_service import get_budget_summary

        db = next(get_db())
        try:
            [row] = get_budget_summary(db, "2026-03")
            assert row["category_name"] == "Groceries"
            assert Decimal(row["spent"]) == EXPECTED_GROCERY_SPEND
            assert Decimal(row["effective_amount"]) == Decimal("100.00")
            assert row["is_over_budget"] is False
            assert row["is_warning"] is True, "86 of 100 is inside the 80% warning band"
        finally:
            db.close()

        assert client.get("/budgets/").status_code == 200

        # --- log out, and everything is guarded again -----------------------
        out = client.post(
            "/auth/logout",
            headers={"Sec-Fetch-Site": "same-origin"},
            follow_redirects=False,
        )
        assert out.status_code == 303
        client.cookies.clear()

        for path in ("/transactions/", "/budgets/", "/accounts/"):
            assert client.get(path, follow_redirects=False).status_code == 307


class TestMvpIdempotency:
    def test_importing_the_same_export_twice_does_not_double_the_budget(self, client):
        """The failure mode that would quietly corrupt every number on screen."""
        _enroll_and_login(client)

        files = {"file": ("ing.csv", ING_CSV, "text/csv")}
        client.post("/transactions/import", files=files)
        client.post("/transactions/import", files={"file": ("ing.csv", ING_CSV, "text/csv")})

        from app.database import get_db
        from app.models.categories import Category
        from app.models.transactions import Transaction
        from app.services.budget_service import compute_monthly_spend

        db = next(get_db())
        try:
            assert db.query(Transaction).count() == 4, "re-import must not duplicate rows"
            groceries = db.query(Category).filter(Category.name == "Groceries").one()
            assert compute_monthly_spend(db, "2026-03")[groceries.id] == (
                EXPECTED_GROCERY_SPEND
            )
        finally:
            db.close()


class TestFirstRunGate:
    def test_setup_token_is_consumed_after_enrollment(self, client):
        _enroll_and_login(client)
        client.cookies.clear()

        # The first-run window must be shut for anonymous callers.
        assert client.get("/auth/totp/setup").status_code == 403
        assert client.get("/auth/webauthn/register/begin").status_code == 403

    def test_wrong_totp_code_does_not_grant_a_session(self, client):
        _enroll_and_login(client)
        client.cookies.clear()

        # A code that is definitely not the current one.
        wrong = f"{(int(pyotp.TOTP(pyotp.random_base32()).now()) + 1) % 1000000:06d}"
        resp = client.post("/auth/totp/verify", data={"code": wrong}, follow_redirects=False)

        assert resp.status_code == 401
        assert client.get("/transactions/", follow_redirects=False).status_code == 307


class TestDashboardWithData:
    def test_dashboard_counts_reflect_the_import(self, client):
        _enroll_and_login(client)
        client.post(
            "/transactions/import",
            files={"file": ("ing.csv", ING_CSV, "text/csv")},
            data={"account_label": "ING Betaalrekening"},
        )

        resp = client.get("/")
        assert resp.status_code == 200
        # 4 transactions across 1 imported account.
        assert "4" in resp.text

        # Sanity: the import created exactly one account, with no Nordigen link.
        from app.database import get_db
        from app.models.accounts import Account

        db = next(get_db())
        try:
            [account] = db.query(Account).all()
            assert account.nordigen_account_id is None
            assert account.account_name == "ING Betaalrekening"
            assert account.created_at <= int(time.time())
        finally:
            db.close()

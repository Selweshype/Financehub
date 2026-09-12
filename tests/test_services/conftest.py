"""Shared fixtures for service-layer tests.

These tests run against a real SQLCipher database rather than mocks, because the
things most worth pinning down — decimal precision, sign handling, the
``booking_date LIKE 'YYYY-MM-%'`` month filter — are exactly the behaviours a
mocked session would paper over.
"""

import time
import uuid
from decimal import Decimal

import pytest

TEST_DB_KEY = "a" * 64
TEST_MASTER_KEY = "b" * 64


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A real, throwaway SQLCipher-backed session with all tables created."""
    import app.config as config_module
    from app.config import (
        AppConfig,
        DatabaseConfig,
        NordigenConfig,
        ResticConfig,
        Secrets,
        TokenEncryptionConfig,
    )
    from app.database import Base, init_db

    db_path = str(tmp_path / "svc.db")
    monkeypatch.setenv("FINANCEHUB_DB_KEY", TEST_DB_KEY)
    monkeypatch.setenv("FINANCEHUB_ENV", "development")

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

    session = db_module._SessionLocal()
    try:
        yield session
    finally:
        session.close()
        config_module._secrets = None


# --------------------------------------------------------------------------- #
# Builders — small helpers so each test reads as the scenario it is describing
# --------------------------------------------------------------------------- #


@pytest.fixture()
def make_category(db):
    def _make(name: str, framework_type: str | None = "wants"):
        from app.models.categories import Category

        cat = Category(
            external_id=str(uuid.uuid4()),
            name=name,
            framework_type=framework_type,
            created_at=int(time.time()),
        )
        db.add(cat)
        db.commit()
        db.refresh(cat)
        return cat

    return _make


@pytest.fixture()
def account(db):
    from app.models.accounts import Account

    acc = Account(
        external_id=str(uuid.uuid4()),
        account_name="Test Account",
        bank_name="Test Bank",
        currency="EUR",
        is_active=1,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture()
def make_transaction(db, account):
    def _make(
        amount: str,
        booking_date: str,
        category_id: int | None = None,
        is_pending: int = 0,
        **kwargs,
    ):
        from app.models.transactions import Transaction

        tx = Transaction(
            external_id=str(uuid.uuid4()),
            account_id=account.id,
            booking_date=booking_date,
            amount=amount,
            currency="EUR",
            category_id=category_id,
            is_pending=is_pending,
            created_at=int(time.time()),
            updated_at=int(time.time()),
            **kwargs,
        )
        db.add(tx)
        db.commit()
        return tx

    return _make


@pytest.fixture()
def make_budget(db):
    def _make(category_id: int, monthly_amount: str, rollover_enabled: int = 0):
        from app.models.budgets import Budget

        budget = Budget(
            external_id=str(uuid.uuid4()),
            category_id=category_id,
            monthly_amount=monthly_amount,
            rollover_enabled=rollover_enabled,
            is_active=1,
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        db.add(budget)
        db.commit()
        db.refresh(budget)
        return budget

    return _make


__all__ = ["Decimal"]

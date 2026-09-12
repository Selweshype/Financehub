"""Verify Alembic migrations against the ORM models.

Every other test builds its schema with ``Base.metadata.create_all``, which means
the migrations — the thing that actually creates the production database — were
never executed by the suite. Migration DDL and the models could drift apart
silently and only diverge on deploy.
"""

import subprocess
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"
TEST_DB_KEY = "a" * 64


def _run_migrations(db_path: Path) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "FINANCEHUB_DB_KEY": TEST_DB_KEY,
        "FINANCEHUB_DB_PATH": str(db_path),
        "FINANCEHUB_ENV": "development",
    }
    return subprocess.run(
        [str(BACKEND / ".venv" / "bin" / "python"), "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory):
    """A database built the way production builds it: by running the migrations."""
    if not (BACKEND / ".venv" / "bin" / "python").exists():
        pytest.skip("backend virtualenv not present")

    db_path = tmp_path_factory.mktemp("mig") / "migrated.db"
    result = _run_migrations(db_path)
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")
    return db_path


def _reflect(db_path: Path) -> dict[str, set[str]]:
    """Return {table: {column, ...}} from a real SQLCipher database."""
    import sqlcipher3.dbapi2 as sqlcipher

    conn = sqlcipher.connect(str(db_path))
    try:
        conn.execute(f"PRAGMA key='{TEST_DB_KEY}'")
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        ]
        return {
            table: {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')")}
            for table in tables
        }
    finally:
        conn.close()


def test_migrations_produce_an_encrypted_database(migrated_db):
    """The migration path must not quietly create a plaintext SQLite file."""
    header = migrated_db.read_bytes()[:16]
    assert not header.startswith(b"SQLite format 3"), (
        "migrated database is NOT encrypted — SQLCipher key was not applied"
    )


def test_every_model_table_exists_after_migration(migrated_db, db):
    """A model with no migration would only fail on deploy."""
    from app.database import Base

    migrated = _reflect(migrated_db)
    missing = sorted(set(Base.metadata.tables) - set(migrated))

    assert not missing, f"models define tables the migrations never create: {missing}"


def test_every_model_column_exists_after_migration(migrated_db, db):
    """Catches a column added to a model without an accompanying migration."""
    from app.database import Base

    migrated = _reflect(migrated_db)

    drift: dict[str, list[str]] = {}
    for table_name, table in Base.metadata.tables.items():
        if table_name not in migrated:
            continue
        model_columns = {c.name for c in table.columns}
        missing = sorted(model_columns - migrated[table_name])
        if missing:
            drift[table_name] = missing

    assert not drift, f"model columns missing from the migrated schema: {drift}"


def test_seed_data_is_present(migrated_db):
    """Migration 0001 seeds the categories and Dutch merchant rules.

    This is why `make init-db` was redundant — nothing else needs to seed.
    """
    import sqlcipher3.dbapi2 as sqlcipher

    conn = sqlcipher.connect(str(migrated_db))
    try:
        conn.execute(f"PRAGMA key='{TEST_DB_KEY}'")
        categories = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        rules = conn.execute("SELECT COUNT(*) FROM categorization_rules").fetchone()[0]
        framework_set = conn.execute(
            "SELECT COUNT(*) FROM categories WHERE framework_type IS NOT NULL"
        ).fetchone()[0]
    finally:
        conn.close()

    assert categories > 0, "no seed categories"
    assert rules > 0, "no seed categorization rules"
    assert framework_set > 0, "migration 0002 did not backfill framework_type"

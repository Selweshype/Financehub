import sys
from logging.config import fileConfig
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models here so Alembic can detect them (populated in Step 2)
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations without a live database connection.

    Useful for generating SQL scripts. Requires sqlalchemy.url to be set
    in alembic.ini — raises RuntimeError immediately if it is missing.
    """
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        print(
            "ERROR: sqlalchemy.url is not set in alembic.ini.\n"
            "Offline SQL generation requires an explicit connection URL.",
            file=sys.stderr,
        )
        sys.exit(1)

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live SQLCipher database.

    The sync_engine is created in database.py (added in Step 2) and
    issues PRAGMA key=? before any DDL so the encrypted DB is accessible.
    """
    from app.database import sync_engine  # noqa: F401 — added in Step 2
    with sync_engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

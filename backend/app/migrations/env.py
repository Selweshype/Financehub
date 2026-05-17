from logging.config import fileConfig
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models here so Alembic can detect them (populated in Step 2)
target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # SQLCipher connection configured in Step 2 (database.py)
    from app.database import sync_engine  # noqa: F401 — added in Step 2
    with sync_engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

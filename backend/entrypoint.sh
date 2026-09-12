#!/bin/bash
set -euo pipefail

AGE_KEY="/secrets/age-key.txt"
SECRETS_FILE="/secrets/secrets.enc.yaml"

# Reads database.key from a YAML document on stdin.
read_db_key() {
    /app/.venv/bin/python -c \
        "import sys, yaml; print(yaml.safe_load(sys.stdin)['database']['key'])"
}

# ------------------------------------------------------------------ #
# Development mode: plaintext secrets, no SOPS, no age key.
#
# This exists so a local deployment can be brought up without generating an
# age key or encrypting a secrets file. It requires BOTH variables, and
# app/config.py enforces the same pair independently — setting only one does
# nothing. Never set these in docker-compose.yml.
# ------------------------------------------------------------------ #
if [ -n "${FINANCEHUB_DEV_SECRETS:-}" ] && [ "${FINANCEHUB_ENV:-}" = "development" ]; then
    if [ ! -f "$FINANCEHUB_DEV_SECRETS" ]; then
        echo "ERROR: FINANCEHUB_DEV_SECRETS is set but no file at $FINANCEHUB_DEV_SECRETS" >&2
        exit 1
    fi
    echo "=============================================================="
    echo "  DEVELOPMENT MODE — secrets are being read in PLAINTEXT from"
    echo "  $FINANCEHUB_DEV_SECRETS"
    echo "  SOPS is not in use. Do not expose this deployment publicly."
    echo "=============================================================="
    FINANCEHUB_DB_KEY="$(read_db_key < "$FINANCEHUB_DEV_SECRETS")"
    export FINANCEHUB_DB_KEY
else
    # Fail fast if required mounts are missing
    if [ ! -f "$AGE_KEY" ]; then
        echo "ERROR: age private key not found at $AGE_KEY" >&2
        echo "ERROR: Bind-mount /etc/financehub/age-key.txt into the container" >&2
        exit 1
    fi

    if [ ! -f "$SECRETS_FILE" ]; then
        echo "ERROR: Encrypted secrets not found at $SECRETS_FILE" >&2
        exit 1
    fi

    # Verify sops can decrypt (fail fast before starting uvicorn).
    # Suppress decrypted output on stdout; let SOPS errors through on stderr.
    if ! sops --decrypt "$SECRETS_FILE" > /dev/null; then
        echo "ERROR: SOPS decryption failed — check age key and secrets file" >&2
        exit 1
    fi

    echo "Secrets decryption: OK"

    # Extract DB key from secrets and export for Alembic / uvicorn
    FINANCEHUB_DB_KEY="$(sops --decrypt "$SECRETS_FILE" | read_db_key)"
    export FINANCEHUB_DB_KEY
fi

export FINANCEHUB_DB_PATH="${FINANCEHUB_DB_PATH:-/data/financehub.db}"

# Ensure data directory exists
mkdir -p "$(dirname "$FINANCEHUB_DB_PATH")"

echo "Running Alembic migrations..."
# Invoke the venv interpreter directly rather than through `uv run`: the
# container now runs with a read-only root filesystem (finding M3) and uv
# wants a writable cache at runtime.
cd /app && /app/.venv/bin/python -m alembic upgrade head
echo "Migrations: OK"

echo "Starting FinanceHub..."

exec /app/.venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --no-access-log

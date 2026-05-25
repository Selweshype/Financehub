#!/bin/bash
set -euo pipefail

AGE_KEY="/secrets/age-key.txt"
SECRETS_FILE="/secrets/secrets.enc.yaml"

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
# Suppress decrypted output on stdout; let SOPS error messages through on stderr.
if ! sops --decrypt "$SECRETS_FILE" > /dev/null; then
    echo "ERROR: SOPS decryption failed — check age key and secrets file" >&2
    exit 1
fi

echo "Secrets decryption: OK"

# Extract DB key from secrets and export for Alembic / uvicorn
DECRYPTED=$(sops --decrypt "$SECRETS_FILE")
export FINANCEHUB_DB_KEY=$(echo "$DECRYPTED" | python3 -c "import sys, yaml; d = yaml.safe_load(sys.stdin); print(d['database']['key'])")
export FINANCEHUB_DB_PATH="${FINANCEHUB_DB_PATH:-/data/financehub.db}"

# Ensure data directory exists
mkdir -p "$(dirname "$FINANCEHUB_DB_PATH")"

echo "Running Alembic migrations..."
cd /app && uv run python -m alembic upgrade head
echo "Migrations: OK"

echo "Starting FinanceHub..."

exec uv run uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --no-access-log

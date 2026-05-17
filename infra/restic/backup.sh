#!/bin/sh
set -eu

SECRETS_FILE="/secrets/secrets.enc.yaml"
AGE_KEY="/secrets/age-key.txt"

if [ ! -f "$AGE_KEY" ] || [ ! -f "$SECRETS_FILE" ]; then
    echo "ERROR: Missing age key or secrets file" >&2
    exit 1
fi

# Decrypt only the restic section we need
RESTIC_PASSWORD=$(sops --decrypt --extract '["restic"]["password"]' "$SECRETS_FILE")
RESTIC_REPOSITORY=$(sops --decrypt --extract '["restic"]["repository"]' "$SECRETS_FILE")

export RESTIC_PASSWORD
export RESTIC_REPOSITORY

echo "Initializing repository if needed..."
restic snapshots > /dev/null 2>&1 || restic init

echo "Running backup..."
restic backup /data --tag financehub

echo "Pruning old snapshots..."
restic forget \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 6 \
    --prune

echo "Verifying repository integrity..."
restic check

echo "Backup complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

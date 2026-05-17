#!/bin/sh
set -eu

SECRETS_FILE="/secrets/secrets.enc.yaml"
AGE_KEY="/secrets/age-key.txt"

if [ ! -f "$AGE_KEY" ] || [ ! -f "$SECRETS_FILE" ]; then
    echo "ERROR: Missing age key or secrets file" >&2
    exit 1
fi

# Tell sops where the age private key lives before any decrypt call
export SOPS_AGE_KEY_FILE="$AGE_KEY"

# Decrypt only the restic credentials we need
RESTIC_PASSWORD=$(sops --decrypt --extract '["restic"]["password"]' "$SECRETS_FILE")
RESTIC_REPOSITORY=$(sops --decrypt --extract '["restic"]["repository"]' "$SECRETS_FILE")

export RESTIC_PASSWORD
export RESTIC_REPOSITORY

# Initialize repo only if it genuinely has not been set up yet.
# "restic cat config" exits 0 when initialized, non-zero with a recognizable
# message when the repo does not exist. Any other error is surfaced as-is.
if ! restic cat config > /dev/null 2>&1; then
    INIT_ERR=$(restic cat config 2>&1 || true)
    case "$INIT_ERR" in
        *"Is there a repository at the given location"*|*"no such file"*|*"repository does not exist"*)
            echo "Repository not initialized — running restic init..."
            restic init
            ;;
        *)
            echo "ERROR: unexpected error checking repository: $INIT_ERR" >&2
            exit 1
            ;;
    esac
fi

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

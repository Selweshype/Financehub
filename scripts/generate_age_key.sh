#!/bin/bash
# Generate age key pair for FinanceHub secrets encryption
set -euo pipefail

KEY_PATH="${1:-/etc/financehub/age-key.txt}"

if [ -f "$KEY_PATH" ]; then
    echo "Key already exists at $KEY_PATH — aborting to prevent overwrite"
    echo "To regenerate, delete the file first and re-run this script"
    exit 1
fi

mkdir -p "$(dirname "$KEY_PATH")"
age-keygen -o "$KEY_PATH"
chmod 600 "$KEY_PATH"

echo ""
echo "Key written to: $KEY_PATH"
echo "Paste the public key above into .sops.yaml"

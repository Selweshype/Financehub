#!/bin/bash
# First-time VPS setup for FinanceHub
set -euo pipefail

echo "=== FinanceHub Bootstrap ==="

# 1. Install system dependencies
apt-get update
apt-get install -y --no-install-recommends \
    docker.io \
    docker-compose-plugin \
    age \
    git \
    curl

# 2. Create secrets directory on host
mkdir -p /etc/financehub
chmod 700 /etc/financehub

# 3. Generate age key if not present
if [ ! -f /etc/financehub/age-key.txt ]; then
    echo "Generating age encryption key..."
    age-keygen -o /etc/financehub/age-key.txt
    chmod 600 /etc/financehub/age-key.txt
    echo ""
    echo ">>> IMPORTANT: Copy the public key above into .sops.yaml <<<"
    echo ">>> Then encrypt your secrets/secrets.yaml and push to the repo <<<"
    echo ""
else
    echo "age key already exists at /etc/financehub/age-key.txt"
fi

# 4. Set up host cron for nightly backup (3 AM)
CRON_JOB="0 3 * * * cd /opt/financehub && docker compose run --rm backup >> /var/log/financehub-backup.log 2>&1"
# Remove only the exact existing entry (if present) before appending the new one
(crontab -l 2>/dev/null | grep -Fxv "$CRON_JOB"; echo "$CRON_JOB") | crontab -
echo "Backup cron job installed"

echo ""
echo "Bootstrap complete. Next steps:"
echo "  1. Update .sops.yaml with your age public key"
echo "  2. Create and encrypt secrets/secrets.yaml"
echo "  3. Update infra/caddy/Caddyfile with your domain"
echo "  4. Run: docker compose up -d"

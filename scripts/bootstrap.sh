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

# 5. Refuse to declare success while config still holds shipped placeholders.
# Finding L4: .sops.yaml keeps a literal REPLACEME recipient, so encryption
# would silently target nothing real. The Caddyfile and compose file carry the
# same example-domain problem.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLACEHOLDERS_FOUND=0

check_placeholder() {
    local file="$1" pattern="$2" hint="$3"
    if [ -f "$REPO_ROOT/$file" ] && grep -q "$pattern" "$REPO_ROOT/$file"; then
        echo "  !! $file still contains a placeholder — $hint" >&2
        PLACEHOLDERS_FOUND=1
    fi
}

echo ""
echo "Checking for unreplaced placeholders..."
check_placeholder ".sops.yaml" "age1REPLACEME" \
    "paste the age public key printed above"
check_placeholder "infra/caddy/Caddyfile" "financehub.example.com" \
    "set your real domain"
check_placeholder "infra/caddy/Caddyfile" "admin@example.com" \
    "set your real ACME contact email"
check_placeholder "docker-compose.yml" "financehub.example.com" \
    "set FINANCEHUB_RP_ID and FINANCEHUB_ORIGIN to your real domain"

if [ "$PLACEHOLDERS_FOUND" -ne 0 ]; then
    echo ""
    echo "Bootstrap INCOMPLETE — fix the placeholders above before starting." >&2
    exit 1
fi

echo "  All placeholders replaced."
echo ""
echo "Bootstrap complete. Next steps:"
echo "  1. Create and encrypt secrets/secrets.yaml -> secrets/secrets.enc.yaml"
echo "  2. Run: docker compose up -d"
echo "  3. Read the first-run SETUP TOKEN from: docker compose logs app"
echo "  4. Enroll a login at https://<your-domain>/auth/webauthn/register?token=<token>"

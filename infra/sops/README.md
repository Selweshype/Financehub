# Secrets Setup (SOPS + age)

## One-time VPS setup

```bash
# Install age
apt-get install -y age

# Generate key pair (run as root or the user that runs Docker)
age-keygen -o /etc/financehub/age-key.txt
chmod 600 /etc/financehub/age-key.txt
chown root:root /etc/financehub/age-key.txt

# The public key is printed to stdout, e.g.:
# Public key: age1abc123...
```

Copy the **public key** into `/.sops.yaml` at the repo root (replace `age1REPLACEME...`).

The **private key** lives at `/etc/financehub/age-key.txt` on the VPS **only**.
Never copy it to your dev machine or commit it.

## Creating / updating secrets

```bash
# On your dev machine (you only need the public key for encryption):
cp secrets/secrets.yaml.example secrets/secrets.yaml
# Fill in all values in secrets/secrets.yaml

# Encrypt:
sops --encrypt secrets/secrets.yaml > secrets/secrets.enc.yaml
rm secrets/secrets.yaml   # always delete plaintext immediately

git add secrets/secrets.enc.yaml
git commit -m "secrets: update encrypted secrets"
```

## Rotating secrets

```bash
# Decrypt → edit → re-encrypt
sops --decrypt secrets/secrets.enc.yaml > secrets/secrets.yaml
# Edit secrets/secrets.yaml
sops --encrypt secrets/secrets.yaml > secrets/secrets.enc.yaml
rm secrets/secrets.yaml

git add secrets/secrets.enc.yaml
git commit -m "rotate: <what changed>"
# On VPS: git pull && docker compose restart app
```

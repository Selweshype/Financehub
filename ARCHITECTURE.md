# FinanceHub Phase 1 — Architecture Plan

## Context

Building a self-hosted personal finance app (single user, EU/Netherlands) that connects to ING and BUNQ via GoCardless Nordigen (PSD2/AISP read-only), auto-imports transactions, and auto-categorizes them Dyme-style. Security is non-negotiable throughout. This document is the ARCHITECTURE.md to be committed to the repository.

---

## 1. Tech Stack

| Layer | Choice | Justification |
|---|---|---|
| Backend | **FastAPI (Python 3.12)** | Fastest single-dev iteration; py_webauthn, pyotp, sqlcipher3 all exist and are maintained; async-native; Pydantic v2 validation; auto OpenAPI for debugging integrations |
| Frontend | **HTMX + Alpine.js + Jinja2** | Zero build toolchain; no npm at runtime; server-rendered HTML with CSP nonce injection; ~20KB total JS; vendored and pinned — eliminates CDN supply chain risk |
| Database | **SQLite + SQLCipher** via `sqlcipher3` | AES-256 at-rest encryption; single file; zero-ops; `sqlcipher3` (Cython wrapper) works with SQLAlchemy 2.x async via custom connection event |
| ORM / Migrations | **SQLAlchemy 2.x (async) + Alembic** | Type-safe; async-native; Alembic handles SQLCipher via `run_sync()` |
| HTTP Client | **httpx (async)** | Used for GoCardless API calls; async, minimal deps |
| Scheduler | **APScheduler 4.x (AsyncIO)** | In-process; no broker/Redis needed; cron syntax; single nightly sync job |
| Auth | **py_webauthn 2.x + pyotp 2.x** | Battle-tested FIDO2 WebAuthn; RFC 6238 TOTP fallback |
| Sessions | **itsdangerous** (already a Starlette dep) | Signed session tokens; `__Host-` prefix cookies |
| Secrets | **SOPS + age** | age key on VPS host only; SOPS-encrypted YAML committed to repo; decrypted once at startup via subprocess — no secret ever touches `os.environ` |
| Reverse Proxy | **Caddy 2.x** | Automatic HTTPS via Let's Encrypt; HTTP/3; minimal config |
| Backup | **Restic** | AES-256 encrypted repository; repo password from SOPS |
| ML Categorization | **scikit-learn + joblib** | TF-IDF + Logistic Regression; local inference; no external API |
| Package Manager | **uv** | Fast, lockfile-based, reproducible builds |

---

## 2. Folder & Project Structure

```
financehub/
├── .sops.yaml                          # SOPS encryption rules (public key only)
├── docker-compose.yml
├── Makefile                            # make dev / build / test / logs / backup
├── README.md
├── ARCHITECTURE.md
│
├── secrets/
│   ├── secrets.enc.yaml                # SOPS-encrypted (committed)
│   └── .gitignore                      # blocks secrets.yaml from being committed
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml                  # all deps, pinned
│   ├── uv.lock
│   ├── entrypoint.sh                   # decrypts secrets → starts uvicorn
│   │
│   └── app/
│       ├── main.py                     # FastAPI app factory + lifespan handler
│       ├── config.py                   # loads SOPS-decrypted secrets into Pydantic models
│       ├── database.py                 # SQLCipher async engine + session factory
│       ├── dependencies.py             # FastAPI dependency injectors (require_auth, get_db)
│       │
│       ├── models/                     # SQLAlchemy ORM models
│       │   ├── user.py
│       │   ├── bank_connection.py
│       │   ├── account.py
│       │   ├── transaction.py
│       │   ├── category.py
│       │   ├── category_rule.py
│       │   ├── sync_log.py
│       │   └── budget_period.py
│       │
│       ├── schemas/                    # Pydantic v2 request/response schemas
│       │   ├── auth.py
│       │   ├── bank.py
│       │   ├── transaction.py
│       │   └── category.py
│       │
│       ├── routers/                    # thin route handlers — validate, call service, return
│       │   ├── auth.py                 # WebAuthn + TOTP endpoints
│       │   ├── banks.py                # GoCardless connection flow
│       │   ├── transactions.py         # list, filter, manual categorize
│       │   ├── categories.py           # CRUD for categories + rules
│       │   ├── dashboard.py            # summary/budget endpoints
│       │   └── admin.py                # sync trigger, health, model retrain
│       │
│       ├── services/                   # all business logic
│       │   ├── auth_service.py         # WebAuthn ceremony logic
│       │   ├── nordigen_client.py      # GoCardless httpx client + token lifecycle
│       │   ├── sync_service.py         # orchestrates full sync flow
│       │   ├── categorization.py       # Layer 1 rules + Layer 2 ML
│       │   └── encryption.py           # AES-GCM token encrypt/decrypt
│       │
│       ├── tasks/
│       │   └── scheduler.py            # APScheduler setup + job definitions
│       │
│       ├── migrations/                 # Alembic
│       │   ├── env.py
│       │   └── versions/
│       │       └── 0001_initial_schema.py
│       │
│       └── templates/                  # Jinja2 HTML (CSP nonce injected per request)
│           ├── base.html
│           ├── partials/               # HTMX fragment responses
│           ├── auth/
│           ├── dashboard/
│           ├── transactions/
│           └── settings/
│
├── static/                             # served directly by Caddy
│   ├── css/app.css                     # hand-written minimal CSS (~400 lines)
│   └── js/
│       ├── htmx.min.js                 # vendored + pinned (no CDN)
│       ├── alpine.min.js               # vendored + pinned
│       └── webauthn.js                 # custom WebAuthn ceremony JS
│
├── infra/
│   ├── caddy/Caddyfile
│   ├── sops/README.md                  # key generation instructions
│   └── restic/backup.sh
│
├── scripts/
│   ├── bootstrap.sh                    # first-time VPS setup
│   ├── generate_age_key.sh
│   ├── init_db.sh                      # run Alembic + seed categories + rules
│   └── rotate_tokens.sh
│
└── tests/
    ├── conftest.py                      # pytest fixtures, in-memory test DB
    ├── test_auth.py
    ├── test_nordigen.py                 # mocked httpx via respx
    ├── test_sync.py
    ├── test_categorization.py
    └── test_api/
```

---

## 3. Database Schema (Phase 1)

All tables in a single SQLCipher-encrypted SQLite file at `/data/financehub.db`. DB key comes from SOPS-decrypted secrets at startup — never from an env var.

### users
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| totp_secret_enc | BLOB NULL | AES-GCM encrypted pyotp secret (double-encrypted: SQLCipher + app-level) |
| totp_enabled | BOOLEAN | DEFAULT FALSE |
| last_login_at | DATETIME NULL | |
| created_at / updated_at | DATETIME | |

### webauthn_credentials
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER FK → users | |
| credential_id | BLOB UNIQUE | |
| public_key | BLOB | COSE-encoded |
| sign_count | INTEGER | replay attack prevention |
| name | TEXT | user-assigned device name |
| last_used_at | DATETIME NULL | |

INDEX: `credential_id`

### bank_connections
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| bank_id | TEXT | e.g. `ING_INGBNL2A`, `BUNQ_BUNQNL2A` |
| bank_name | TEXT | human readable |
| requisition_id | TEXT UNIQUE | Nordigen stable ID |
| status | TEXT | `CREATED` \| `LINKED` \| `EXPIRED` \| `ERROR` |
| link_url | TEXT NULL | OAuth redirect URL |
| link_expires_at | DATETIME NULL | ~90 days from creation |
| access_token_enc | BLOB NULL | AES-GCM encrypted, 24h lifetime |
| access_token_expires_at | DATETIME NULL | |
| refresh_token_enc | BLOB NULL | AES-GCM encrypted, 30d lifetime |
| refresh_token_expires_at | DATETIME NULL | |
| last_synced_at | DATETIME NULL | |

INDEX: `status`, `bank_id`

### accounts
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| bank_connection_id | INTEGER FK | |
| nordigen_account_id | TEXT UNIQUE | Nordigen internal UUID |
| iban_hash | TEXT | SHA-256(IBAN) — dedup only, full IBAN never stored |
| iban_display | TEXT | masked: `NL91 INGB **** **** 1234` |
| bank_name | TEXT | |
| currency | TEXT | DEFAULT 'EUR' |
| current_balance | DECIMAL(12,2) NULL | |
| available_balance | DECIMAL(12,2) NULL | |
| balance_updated_at | DATETIME NULL | |
| is_active | BOOLEAN | DEFAULT TRUE |

INDEX: `bank_connection_id`, `nordigen_account_id`

### categories
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| name | TEXT UNIQUE | |
| slug | TEXT UNIQUE | e.g. `groceries` |
| icon | TEXT | SVG icon name |
| color | TEXT | hex color |
| is_system | BOOLEAN | seeded defaults — not user-deletable |
| is_income | BOOLEAN | |
| parent_id | INTEGER NULL FK → categories | subcategories |
| display_order | INTEGER | |

Seeded system categories: Groceries, Dining, Transport, Rent/Housing, Utilities, Subscriptions, Healthcare, Shopping, Entertainment, Personal Care, Travel, ATM/Cash, Income, Transfers, Uncategorized.

### transactions
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| account_id | INTEGER FK | |
| category_id | INTEGER FK NULL | |
| nordigen_transaction_id | TEXT UNIQUE | primary dedup key |
| content_hash | TEXT | SHA-256(date+amount+description) — secondary dedup |
| booking_date | DATE | |
| value_date | DATE NULL | |
| amount | DECIMAL(12,2) | negative=debit, positive=credit |
| currency | TEXT | DEFAULT 'EUR' |
| description | TEXT | creditorName or remittanceInfo |
| merchant_name | TEXT NULL | normalized, extracted from description |
| counterparty_iban_hash | TEXT NULL | SHA-256(counterparty IBAN) — no raw IBAN |
| category_source | TEXT | `uncategorized` \| `rule` \| `ml` \| `manual` |
| category_confidence | REAL NULL | 0.0–1.0 for `ml` source |
| is_pending | BOOLEAN | |
| raw_data_hash | TEXT | SHA-256 of full Nordigen JSON — audit without storing PII |
| notes | TEXT NULL | user notes |

INDEXES: `account_id`, `booking_date DESC`, `category_id`, `nordigen_transaction_id`, `content_hash`, `merchant_name`
COMPOUND: `(account_id, booking_date DESC)`

### category_rules
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| category_id | INTEGER FK | |
| rule_type | TEXT | `keyword` \| `regex` \| `merchant_exact` |
| pattern | TEXT | match string or regex |
| field_target | TEXT | `description` \| `merchant_name` |
| is_case_sensitive | BOOLEAN | DEFAULT FALSE |
| priority | INTEGER | lower = evaluated first |
| is_active | BOOLEAN | |

INDEX: `priority ASC`, partial index on `is_active = TRUE`

### sync_log
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| started_at | DATETIME | |
| finished_at | DATETIME NULL | |
| status | TEXT | `running` \| `success` \| `partial` \| `failed` |
| trigger | TEXT | `scheduled` \| `manual` |
| accounts_synced | INTEGER | |
| transactions_fetched / imported / skipped | INTEGER | |
| error_summary | TEXT NULL | brief text, no PII |
| duration_seconds | REAL NULL | |

### budget_periods
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| category_id | INTEGER FK | |
| period_month | TEXT | `2026-04` format |
| budget_amount | DECIMAL(12,2) | |

UNIQUE: `(category_id, period_month)`

---

## 4. GoCardless Nordigen Integration Flow

### API Overview
- Base URL: `https://bankaccountdata.gocardless.com/api/v2/`
- Two-token system: **access_token** (24h) + **refresh_token** (30d), separate from requisition
- Requisition = bank consent session, stable `requisition_id`, valid ~90 days

### Phase A: Initial Bank Connection

```
User clicks "Connect ING"
  → POST /api/banks/connect { bank_id: "ING_INGBNL2A" }
  → NordigenClient.create_requisition(institution_id, redirect_url, reference=uuid4())
  → Nordigen returns: { id: "req_abc", link: "https://ob.nordigen.com/...", status: "CR" }
  → Store bank_connections: status=CREATED, link_url, link_expires_at=now+90d
  → Redirect user to link_url (bank's Open Banking portal)
  → Bank redirects back to: /banks/callback?ref=<reference>
  → GET /api/v2/requisitions/{requisition_id}/ → verify status="LN" (Linked)
  → Update bank_connections: status=LINKED
  → Run account discovery (Phase B)
```

### Phase B: Account Discovery (post-link)

```
GET /api/v2/requisitions/{req_id}/ → accounts: [uuid1, uuid2]
For each account UUID:
  GET /api/v2/accounts/{uuid}/details/ → iban, name, currency
  GET /api/v2/accounts/{uuid}/balances/ → current balance

Store in accounts:
  nordigen_account_id = UUID
  iban_hash = SHA-256(iban)         ← full IBAN never stored
  iban_display = mask_iban(iban)    ← "NL91 INGB **** **** 1234"
```

### Phase C: Token Lifecycle

```
Before every API call:
  1. Decrypt access_token_enc; check expires_at - now() < 5 minutes
  2. If near expiry → POST /api/v2/token/refresh/ { refresh: <decrypted_refresh> }
     → Re-encrypt new access token → store
  3. If refresh_token also expired (>30d):
     → POST /api/v2/token/new/ { secret_id, secret_key }  ← from SOPS config
     → Re-encrypt and store both tokens

Token encryption:
  key = HKDF(master_secret, salt="token-encryption", length=32)
  nonce = os.urandom(12)
  blob = nonce || AES-GCM(key, nonce, plaintext_token)   ← first 12 bytes = nonce
```

### Phase D: Daily Sync (APScheduler cron: 04:00 Europe/Amsterdam)

```
SyncService.run_full_sync():
  1. Create sync_log row (status=running)
  2. For each bank_connection WHERE status=LINKED:
     a. Ensure valid access token
     b. For each account:
        i.  GET /accounts/{id}/transactions/?date_from=last_sync-2d  (2d overlap for delayed postings)
        ii. GET /accounts/{id}/balances/ → update current_balance
        iii. Process each transaction (Phase E)
  3. Update sync_log (success/partial/failed, duration)
```

### Phase E: Transaction Processing & Deduplication

```
For each raw transaction:
  content_hash = SHA-256(f"{booking_date}{amount}{description}")
  raw_data_hash = SHA-256(json.dumps(tx, sort_keys=True))

  Dedup (in order):
    1. SELECT id WHERE nordigen_transaction_id = tx.transactionId → skip if exists
    2. SELECT id WHERE content_hash = ? AND account_id = ? → skip if exists

  If new:
    merchant_name = extract_merchant(creditorName → debtorName → remittanceInfo)
    Normalize: strip card numbers, strip prefixes, title-case
    category_id, source, confidence = categorize(merchant_name, description)
    INSERT INTO transactions (...)
```

### ING vs BUNQ Notes

| | ING (`ING_INGBNL2A`) | BUNQ (`BUNQ_BUNQNL2A`) |
|---|---|---|
| Main description field | `creditorName` (clean) | `remittanceInformationUnstructured` (less structured) |
| transactionId stability | Stable ✓ | Stable ✓ (longer UUID format) |
| Balance field | Use `interimAvailable` | Use `interimAvailable` |
| Quirks | Dutch direct debits have `mandateId` | Savings goals appear as separate accounts |

### Error Handling

```
429 Too Many Requests → exponential backoff: 2^n × 1s, max 5 retries
401 Unauthorized → attempt token refresh once → mark ERROR on failure
403 Forbidden → requisition expired/revoked → status=EXPIRED, surface reconnect banner
500/502/503 → retry 3× with backoff → mark sync as "partial"

Requisition expiry warning: at T-7 days, add warning to sync_log.error_summary + UI banner
```

---

## 5. Auto-Categorization Logic (Dyme-Style)

Dyme uses a curated Dutch merchant database + pattern matching for ~80% of volume, then ML for the long tail, with user overrides feeding back into rules.

### Layer 1: Keyword/Regex Rules Engine

```python
# Evaluated in priority ASC order (lower number = evaluated first)
for rule in active_rules_ordered_by_priority:
    field_value = tx.merchant_name if rule.field_target == 'merchant_name' else tx.description
    if rule.rule_type == 'merchant_exact':
        match = field_value.strip().lower() == rule.pattern.strip().lower()
    elif rule.rule_type == 'keyword':
        match = rule.pattern.lower() in field_value.lower()
    elif rule.rule_type == 'regex':
        match = re.search(rule.pattern, field_value, re.IGNORECASE)
    if match:
        return category_id, source='rule', confidence=1.0

# No match → Layer 2
```

**Priority system:**

| Range | Type |
|---|---|
| 1–9 | System exact merchant (highest confidence) |
| 10–49 | User exact merchant overrides |
| 50–99 | System keyword/regex |
| 100–149 | User keyword/regex |
| 200+ | Catch-all fallbacks |

**Seeded Dutch rules (examples):**

| Priority | Pattern | Field | Type | Category |
|---|---|---|---|---|
| 1 | Albert Heijn | merchant_name | merchant_exact | Groceries |
| 1 | Jumbo | merchant_name | merchant_exact | Groceries |
| 1 | Lidl / Aldi / Plus | merchant_name | merchant_exact | Groceries |
| 1 | NS | merchant_name | merchant_exact | Transport |
| 1 | Spotify / Netflix | merchant_name | merchant_exact | Subscriptions |
| 1 | Ziggo | merchant_name | merchant_exact | Utilities |
| 50 | APOTHEEK | description | keyword | Healthcare |
| 50 | OV-CHIPKAART | description | keyword | Transport |
| 50 | BELASTING | description | keyword | Utilities |
| 50 | SALARIS / LOON | description | keyword | Income |
| 50 | TIKKIE | merchant_name | keyword | Transfers |
| 50 | THUISBEZORGD / UBER EATS | description | keyword | Dining |

### Layer 2: ML Fallback (local, no external API)

```python
# sklearn Pipeline
Pipeline([
    TfidfVectorizer(
        analyzer='char_wb',      # character n-grams — better for Dutch compound words
        ngram_range=(2, 4),
        max_features=5000,
        sublinear_tf=True
    ),
    LogisticRegression(C=1.0, max_iter=1000)
])

# Input: merchant_name + " " + description
# Output: (category_id, confidence)

if confidence < 0.5:
    # → category_id = Uncategorized, source = 'ml_low_confidence'
else:
    # → source = 'ml'

# Model persistence: joblib.dump() → /models/categorization_model.pkl
# Retrain triggers: manual admin button OR every 50 manual overrides
# Bootstrap: use rule-categorized transactions as initial training data (≥30 needed)
```

### Confidence UI + Override

| Source | UI Display |
|---|---|
| `rule` | Category shown, no badge |
| `ml` ≥ 0.8 | Subtle green dot |
| `ml` 0.5–0.79 | Yellow "?" badge — encourage review |
| `ml_low_confidence` | "Uncategorized" highlighted orange |
| `manual` | Category shown, no badge |

Override flow: click category → HTMX dropdown → `PATCH /api/transactions/{id}/category` → optional "Create rule for this merchant?" prompt → if yes, auto-creates `merchant_exact` rule.

---

## 6. Docker Compose Layout

```yaml
networks:
  frontend:             # caddy ↔ app
    driver: bridge
    internal: false     # caddy needs internet for ACME
  backend:              # app-internal only
    driver: bridge
    internal: true

volumes:
  db_data:              # SQLCipher encrypted database
  caddy_data:           # TLS certificates
  caddy_config:
  ml_models:            # trained categorization models
  restic_cache:

services:
  app:
    build: ./backend
    restart: unless-stopped
    networks: [frontend, backend]
    volumes:
      - db_data:/data
      - ml_models:/models
      - /etc/financehub/age-key.txt:/secrets/age-key.txt:ro   # host bind mount
      - ./secrets/secrets.enc.yaml:/secrets/secrets.enc.yaml:ro
    expose: ["8000"]     # NOT published to host — caddy-only
    environment:
      - SOPS_AGE_KEY_FILE=/secrets/age-key.txt   # path only, not the key
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 512M }

  caddy:
    image: caddy:2.8-alpine
    restart: unless-stopped
    networks: [frontend]
    ports: ["80:80", "443:443", "443:443/udp"]
    volumes:
      - ./infra/caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - ./static:/srv/static:ro      # served directly by Caddy
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      app: { condition: service_healthy }
    deploy:
      resources:
        limits: { cpus: "0.5", memory: 128M }

  backup:
    image: restic/restic:0.16.4
    restart: "no"        # triggered by host cron: docker compose run --rm backup
    networks: []         # no network needed for backup prep
    volumes:
      - db_data:/data:ro
      - restic_cache:/root/.cache/restic
      - /etc/financehub/age-key.txt:/secrets/age-key.txt:ro
      - ./secrets/secrets.enc.yaml:/secrets/secrets.enc.yaml:ro
      - ./infra/restic/backup.sh:/backup.sh:ro
    environment:
      - SOPS_AGE_KEY_FILE=/secrets/age-key.txt
    entrypoint: ["/bin/sh", "/backup.sh"]
```

### Caddyfile

```
{
    email admin@example.com
    admin off
}

financehub.example.com {
    tls {
        protocols tls1.2 tls1.3
    }

    handle /static/* {
        root * /srv
        file_server
        header Cache-Control "public, max-age=31536000, immutable"
    }

    handle /healthz {
        respond "OK" 200
    }

    reverse_proxy app:8000 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }

    # Static security headers (CSP set per-request by FastAPI middleware — nonce-based)
    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        Permissions-Policy "geolocation=(), microphone=(), camera=()"
        Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
        -Server
    }
}
```

Note: CSP is NOT set in Caddy — it requires a per-request nonce from FastAPI middleware, injected into Jinja2 template context.

---

## 7. Secrets Management (SOPS + age)

### age Key — VPS Setup

```bash
# Run once on VPS during bootstrap
apt-get install age
age-keygen -o /etc/financehub/age-key.txt
chmod 600 /etc/financehub/age-key.txt
chown root:root /etc/financehub/age-key.txt
# Public key from output → paste into .sops.yaml
# Private key stays on VPS ONLY — never copied to dev machine
```

### .sops.yaml (committed to repo — public key only)

```yaml
creation_rules:
  - path_regex: secrets/secrets\.enc\.yaml$
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### Secrets Structure

```yaml
# secrets/secrets.yaml  ← NEVER committed (.gitignore blocks it)
database:
  key: "<64-hex-random>"          # SQLCipher DB encryption key
app:
  secret_key: "<64-hex-random>"   # itsdangerous session signing
nordigen:
  secret_id: "<uuid>"
  secret_key: "<string>"
token_encryption:
  master_key: "<64-hex-random>"   # AES-GCM key derivation for stored tokens
restic:
  password: "<strong-random>"
  repository: "s3:..."            # or B2/SFTP
```

```bash
# Encrypt: run on dev machine with age public key available
sops --encrypt secrets/secrets.yaml > secrets/secrets.enc.yaml
rm secrets/secrets.yaml   # always delete plaintext after encrypting
git add secrets/secrets.enc.yaml
```

### How FastAPI Reads Secrets at Startup

```python
# app/config.py — called once in lifespan handler
def load_secrets() -> AppSecrets:
    result = subprocess.run(
        ["sops", "--decrypt", "/secrets/secrets.enc.yaml"],
        capture_output=True, text=True,
        env={"SOPS_AGE_KEY_FILE": "/secrets/age-key.txt", "PATH": "/usr/local/bin:/usr/bin:/bin"},
        timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(f"SOPS decryption failed ({result.returncode})")  # no key material in log
    return AppSecrets(**yaml.safe_load(result.stdout))
```

Secrets held in memory as Pydantic model. No secret ever touches `os.environ`. The `sops` binary is installed in the Docker image (download + SHA-256 verify in Dockerfile).

### Rotation Procedures

**GoCardless tokens** (within DB): rotated automatically by sync service. Manual trigger:
```bash
docker compose exec app python -c "
from app.services.sync_service import force_token_rotation
import asyncio; asyncio.run(force_token_rotation(bank_connection_id=1))
"
```

**SOPS secrets** (e.g., new Nordigen credentials):
```bash
sops --decrypt secrets/secrets.enc.yaml > secrets/secrets.yaml
# edit secrets/secrets.yaml
sops --encrypt secrets/secrets.yaml > secrets/secrets.enc.yaml
rm secrets/secrets.yaml
git add secrets/secrets.enc.yaml && git commit -m "rotate: update nordigen credentials"
# On VPS: git pull && docker compose restart app
```

---

## 8. Step-by-Step Build Order

| # | Task | Est. Days | Cumulative |
|---|---|---|---|
| 1 | Repo + Docker skeleton + Makefile + Caddyfile | 2 | 2 |
| 2 | SQLCipher DB layer (engine + all ORM models + Alembic) | 2 | 4 |
| 3 | SOPS secrets integration (config.py + entrypoint.sh + Dockerfile) | 1 | 5 |
| 4 | Authentication (WebAuthn + TOTP + CSP middleware + login UI) | 3 | 8 |
| 5 | GoCardless integration (nordigen_client.py + bank connection flow) | 4 | 12 |
| 6 | Transaction sync engine (sync_service + dedup + APScheduler) | 3 | 15 |
| 7 | Auto-categorization (rule engine + seeded Dutch rules + ML layer) | 3 | 18 |
| 8 | Frontend UI (dashboard + transactions + categories + settings) | 6 | 24 |
| 9 | Restic backup (backup.sh + host cron + restore test) | 2 | 26 |
| 10 | Production hardening (log audit, rate limiting, bandit, deploy) | 4 | 30 |

**Total: ~30 developer-days** (6–8 weeks part-time / 3–4 weeks focused)

### Recommended Build Sequence Rationale

Steps 1–3 form the **security foundation** — nothing else builds without them. Step 4 (auth) gates all UI. Step 5 (GoCardless) can be tested with a real account immediately after. Steps 6–7 are the core value. Step 8 is last because HTMX partial endpoints are built incrementally alongside the backend they call.

---

## Security Cross-Reference

| Requirement | Implementation |
|---|---|
| API tokens encrypted at rest | AES-GCM (`cryptography` lib) via `encryption.py`; HKDF-derived key from SOPS master secret |
| SQLCipher-encrypted SQLite | `sqlcipher3` + SQLAlchemy `PRAGMA key=?` connection event |
| Passkeys (WebAuthn) | `py_webauthn` 2.x — full registration + authentication ceremony |
| TOTP fallback | `pyotp`; secret double-encrypted (SQLCipher + AES-GCM) |
| Caddy HTTPS | Automatic Let's Encrypt; TLS 1.2+ only; HTTP/3 |
| Docker network isolation | `app` not port-published; only reachable via caddy on `frontend` network |
| No raw credentials in env vars | SOPS subprocess at startup; only `SOPS_AGE_KEY_FILE` (a path) in env |
| `__Host-` session cookies | FastAPI response headers via `itsdangerous` |
| CSP nonce-based | Per-request nonce in FastAPI middleware; injected into every Jinja2 template |
| No PII in logs | Explicit audit pass at Step 10; no f-string logging of IBANs/amounts/tokens |
| Restic encrypted backups | Restic password from SOPS; AES-256 repository encryption |

---

## Critical Files

| File | Why Critical |
|---|---|
| `backend/app/config.py` | Security foundation — SOPS decrypt at startup; all secrets flow from here |
| `backend/app/database.py` | SQLCipher engine init; custom `PRAGMA key=?` connection event |
| `backend/app/services/nordigen_client.py` | GoCardless HTTP client + token lifecycle (most complex stateful logic) |
| `backend/app/services/categorization.py` | Two-layer categorization engine with confidence scoring |
| `backend/app/services/encryption.py` | AES-GCM token encrypt/decrypt for bank_connections table |
| `docker-compose.yml` | Network isolation + secret bind-mounts; correctness = security posture |
| `.sops.yaml` | SOPS encryption rules; must reference correct age public key |
| `secrets/secrets.enc.yaml` | Encrypted secrets committed to repo — decrypted only on VPS at runtime |

---

## Dependency List (pyproject.toml)

```toml
[project]
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.115.*",
    "uvicorn[standard]==0.32.*",
    "python-multipart==0.0.17",
    "jinja2==3.1.*",
    "httpx==0.28.*",
    "sqlalchemy[asyncio]==2.0.*",
    "aiosqlite==0.20.*",
    "sqlcipher3==0.5.*",
    "alembic==1.14.*",
    "py-webauthn==2.2.*",
    "pyotp==2.9.*",
    "itsdangerous==2.2.*",
    "qrcode==8.0.*",
    "cryptography==44.*",
    "pyyaml==6.0.*",
    "apscheduler==4.0.*",
    "scikit-learn==1.6.*",
    "joblib==1.4.*",
    "pydantic==2.10.*",
    "pydantic-settings==2.7.*",
]

[tool.uv.dev-dependencies]
dev = [
    "pytest==8.3.*",
    "pytest-asyncio==0.24.*",
    "respx==0.21.*",
    "bandit==1.8.*",
    "ruff==0.8.*",
]
```

"""Initial schema — all Phase 1 tables, seed categories and Dutch merchant rules.

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00
"""
from __future__ import annotations

import time
import uuid

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # nordigen_requisitions
    # ------------------------------------------------------------------ #
    op.create_table(
        "nordigen_requisitions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column("nordigen_requisition_id", sa.Text, unique=True, nullable=False),
        sa.Column("institution_id", sa.Text),
        sa.Column("bank_name", sa.Text),
        sa.Column("status", sa.Text),
        sa.Column("link", sa.Text),
        sa.Column("initiated_at", sa.Integer),
        sa.Column("linked_at", sa.Integer),
        sa.Column("expires_at", sa.Integer),
        sa.Column("last_synced_at", sa.Integer),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # accounts
    # ------------------------------------------------------------------ #
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column("nordigen_account_id", sa.Text, unique=True),
        sa.Column(
            "requisition_id",
            sa.Integer,
            sa.ForeignKey("nordigen_requisitions.id", ondelete="SET NULL"),
        ),
        sa.Column("iban", sa.Text),           # AES-GCM encrypted
        sa.Column("bank_name", sa.Text),
        sa.Column("account_name", sa.Text),
        sa.Column("currency", sa.Text, nullable=False, server_default="EUR"),
        sa.Column("balance_amount", sa.Text),  # decimal as TEXT
        sa.Column("balance_type", sa.Text),
        sa.Column("balance_updated_at", sa.Integer),
        sa.Column("is_active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # categories
    # ------------------------------------------------------------------ #
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column("name", sa.Text, unique=True, nullable=False),
        sa.Column("name_nl", sa.Text),
        sa.Column("icon", sa.Text),
        sa.Column("color", sa.Text),
        sa.Column(
            "parent_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
        ),
        sa.Column("is_system", sa.Integer, nullable=False, server_default="0"),
        sa.Column("display_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # categorization_rules
    # ------------------------------------------------------------------ #
    op.create_table(
        "categorization_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column(
            "category_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field", sa.Text, nullable=False),
        sa.Column("match_type", sa.Text, nullable=False),  # exact|contains|starts_with|regex
        sa.Column("pattern", sa.Text, nullable=False),
        sa.Column("is_case_sensitive", sa.Integer, nullable=False, server_default="0"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("is_active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_system", sa.Integer, nullable=False, server_default="0"),
        sa.Column("hit_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_hit_at", sa.Integer),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # transactions
    # ------------------------------------------------------------------ #
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nordigen_transaction_id", sa.Text, unique=True),
        sa.Column("booking_date", sa.Text),   # YYYY-MM-DD
        sa.Column("value_date", sa.Text),     # YYYY-MM-DD
        sa.Column("amount", sa.Text, nullable=False),  # decimal as TEXT
        sa.Column("currency", sa.Text, nullable=False, server_default="EUR"),
        sa.Column("creditor_name", sa.Text),
        sa.Column("creditor_iban", sa.Text),  # AES-GCM encrypted
        sa.Column("debtor_name", sa.Text),
        sa.Column("debtor_iban", sa.Text),    # AES-GCM encrypted
        sa.Column("remittance_information", sa.Text),
        sa.Column("proprietary_bank_code", sa.Text),
        sa.Column(
            "category_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
        ),
        sa.Column("categorization_source", sa.Text),  # 'rule'|'manual'|'default'
        sa.Column(
            "categorization_rule_id",
            sa.Integer,
            sa.ForeignKey("categorization_rules.id", ondelete="SET NULL"),
        ),
        sa.Column("is_pending", sa.Integer, nullable=False, server_default="0"),
        sa.Column("imported_at", sa.Integer),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # nordigen_tokens
    # ------------------------------------------------------------------ #
    op.create_table(
        "nordigen_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("access_token", sa.Text, nullable=False),   # AES-GCM encrypted
        sa.Column("access_expires_at", sa.Integer),
        sa.Column("refresh_token", sa.Text, nullable=False),  # AES-GCM encrypted
        sa.Column("refresh_expires_at", sa.Integer),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # webauthn_credentials
    # ------------------------------------------------------------------ #
    op.create_table(
        "webauthn_credentials",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("credential_id", sa.Text, unique=True, nullable=False),
        sa.Column("public_key", sa.Text, nullable=False),
        sa.Column("sign_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("aaguid", sa.Text),
        sa.Column("device_name", sa.Text),
        sa.Column("backed_up", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.Integer),
        sa.Column("created_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # totp_secrets
    # ------------------------------------------------------------------ #
    op.create_table(
        "totp_secrets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("secret", sa.Text, nullable=False),  # AES-GCM encrypted
        sa.Column("is_active", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("activated_at", sa.Integer),
    )

    # ------------------------------------------------------------------ #
    # sessions
    # ------------------------------------------------------------------ #
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.Text, unique=True, nullable=False),  # SHA-256
        sa.Column("auth_method", sa.Text),   # 'webauthn' | 'totp'
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("last_seen_at", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.Integer, nullable=False),
        sa.Column("ip_address", sa.Text),
        sa.Column("user_agent_hash", sa.Text),
    )

    # ------------------------------------------------------------------ #
    # sync_log
    # ------------------------------------------------------------------ #
    op.create_table(
        "sync_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "account_id",
            sa.Integer,
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("synced_at", sa.Integer, nullable=False),
        sa.Column("status", sa.Text),  # 'success' | 'error'
        sa.Column("error_message", sa.Text),
        sa.Column("transactions_added", sa.Integer, nullable=False, server_default="0"),
    )

    # ------------------------------------------------------------------ #
    # Seed: system categories
    # ------------------------------------------------------------------ #
    now = int(time.time())
    categories_table = sa.table(
        "categories",
        sa.column("external_id", sa.Text),
        sa.column("name", sa.Text),
        sa.column("name_nl", sa.Text),
        sa.column("icon", sa.Text),
        sa.column("color", sa.Text),
        sa.column("is_system", sa.Integer),
        sa.column("display_order", sa.Integer),
        sa.column("created_at", sa.Integer),
    )

    seed_categories = [
        ("Groceries",       "Boodschappen",        "🛒", "#4CAF50"),
        ("Dining & Takeout","Eten & Afhalen",       "🍽️", "#FF9800"),
        ("Transport",       "Vervoer",              "🚂", "#2196F3"),
        ("Housing",         "Wonen",                "🏠", "#9C27B0"),
        ("Utilities",       "Nutsvoorzieningen",    "⚡", "#FF5722"),
        ("Healthcare",      "Zorg",                 "🏥", "#F44336"),
        ("Shopping",        "Winkelen",             "🛍️", "#E91E63"),
        ("Entertainment",   "Ontspanning",          "🎬", "#673AB7"),
        ("Subscriptions",   "Abonnementen",         "📺", "#00BCD4"),
        ("Salary",          "Salaris",              "💰", "#8BC34A"),
        ("Savings",         "Sparen",               "🏦", "#009688"),
        ("Transfers",       "Overschrijvingen",     "↔️", "#607D8B"),
        ("Fees & Charges",  "Kosten",               "💳", "#795548"),
        ("Other",           "Overig",               "❓", "#9E9E9E"),
    ]

    op.bulk_insert(
        categories_table,
        [
            {
                "external_id": str(uuid.uuid4()),
                "name": name,
                "name_nl": name_nl,
                "icon": icon,
                "color": color,
                "is_system": 1,
                "display_order": idx,
                "created_at": now,
            }
            for idx, (name, name_nl, icon, color) in enumerate(seed_categories)
        ],
    )

    # ------------------------------------------------------------------ #
    # Seed: Dutch merchant categorization rules (is_system=1)
    # ------------------------------------------------------------------ #
    rules_table = sa.table(
        "categorization_rules",
        sa.column("external_id", sa.Text),
        sa.column("category_id", sa.Integer),
        sa.column("field", sa.Text),
        sa.column("match_type", sa.Text),
        sa.column("pattern", sa.Text),
        sa.column("is_case_sensitive", sa.Integer),
        sa.column("priority", sa.Integer),
        sa.column("is_active", sa.Integer),
        sa.column("is_system", sa.Integer),
        sa.column("hit_count", sa.Integer),
        sa.column("last_hit_at", sa.Integer),
        sa.column("created_at", sa.Integer),
        sa.column("updated_at", sa.Integer),
    )

    # Map name → (field, match_type, pattern, priority)
    # category_id resolved by SELECT after insert — use inline subselect trick
    # Instead we use op.execute() with raw SQL for seed rules.

    conn = op.get_bind()

    def cat_id(name: str) -> int:
        row = conn.execute(
            sa.text("SELECT id FROM categories WHERE name = :n"), {"n": name}
        ).fetchone()
        assert row, f"Seed category '{name}' not found"
        return row[0]

    groceries_id      = cat_id("Groceries")
    transport_id      = cat_id("Transport")
    dining_id         = cat_id("Dining & Takeout")
    subscriptions_id  = cat_id("Subscriptions")
    utilities_id      = cat_id("Utilities")
    transfers_id      = cat_id("Transfers")
    salary_id         = cat_id("Salary")
    healthcare_id     = cat_id("Healthcare")

    merchant_rules: list[tuple[int, str, str, str, int]] = [
        # (category_id, field, match_type, pattern, priority)
        # Groceries
        (groceries_id,     "creditor_name", "starts_with", "Albert Heijn",   10),
        (groceries_id,     "creditor_name", "starts_with", "AH ",            10),
        (groceries_id,     "creditor_name", "contains",    "Jumbo",          10),
        (groceries_id,     "creditor_name", "contains",    "Lidl",           10),
        (groceries_id,     "creditor_name", "contains",    "Aldi",           10),
        (groceries_id,     "creditor_name", "contains",    "Plus Supermarkt",10),
        (groceries_id,     "creditor_name", "contains",    "Dirk",           10),
        (groceries_id,     "remittance_information", "contains", "Albert Heijn", 15),
        (groceries_id,     "remittance_information", "contains", "Jumbo",     15),
        # Transport
        (transport_id,     "creditor_name", "starts_with", "NS ",            10),
        (transport_id,     "creditor_name", "contains",    "OV-Chipkaart",   10),
        (transport_id,     "creditor_name", "contains",    "GVB",            10),
        (transport_id,     "creditor_name", "contains",    "Connexxion",     10),
        (transport_id,     "creditor_name", "contains",    "Arriva",         10),
        (transport_id,     "creditor_name", "contains",    "Uber",           20),
        (transport_id,     "remittance_information", "contains", "OV-Chipkaart", 15),
        # Dining & Takeout
        (dining_id,        "creditor_name", "contains",    "Thuisbezorgd",   10),
        (dining_id,        "creditor_name", "contains",    "Uber Eats",      10),
        (dining_id,        "creditor_name", "contains",    "Deliveroo",      10),
        # Subscriptions
        (subscriptions_id, "creditor_name", "contains",    "Spotify",        10),
        (subscriptions_id, "creditor_name", "contains",    "Netflix",        10),
        (subscriptions_id, "creditor_name", "contains",    "Disney+",        10),
        (subscriptions_id, "creditor_name", "contains",    "Videoland",      10),
        (subscriptions_id, "remittance_information", "contains", "Spotify",  15),
        (subscriptions_id, "remittance_information", "contains", "Netflix",  15),
        # Utilities
        (utilities_id,     "creditor_name", "contains",    "Ziggo",          10),
        (utilities_id,     "creditor_name", "contains",    "KPN",            10),
        (utilities_id,     "creditor_name", "contains",    "Eneco",          10),
        (utilities_id,     "creditor_name", "contains",    "Essent",         10),
        (utilities_id,     "creditor_name", "contains",    "T-Mobile",       10),
        (utilities_id,     "remittance_information", "contains", "Ziggo",    15),
        (utilities_id,     "remittance_information", "contains", "KPN",      15),
        # Transfers
        (transfers_id,     "remittance_information", "contains", "Tikkie",    5),
        (transfers_id,     "creditor_name", "contains",    "Tikkie",          5),
        # Salary
        (salary_id,        "remittance_information", "contains", "Salaris",   5),
        (salary_id,        "remittance_information", "contains", "Loon",      5),
        (salary_id,        "remittance_information", "contains", "Maandloon", 5),
        (salary_id,        "creditor_name", "contains",    "Salaris",         5),
        # Healthcare
        (healthcare_id,    "creditor_name", "contains",    "Apotheek",       10),
        (healthcare_id,    "creditor_name", "contains",    "Tandarts",       10),
        (healthcare_id,    "creditor_name", "contains",    "Zorgverzekering",10),
        (healthcare_id,    "creditor_name", "contains",    "CZ",             10),
        (healthcare_id,    "creditor_name", "contains",    "Menzis",         10),
        (healthcare_id,    "remittance_information", "contains", "Zorgverzekering", 15),
        (healthcare_id,    "remittance_information", "contains", "Apotheek",  15),
        # Extra well-known Dutch merchants
        (groceries_id,     "creditor_name", "contains",    "Dekamarkt",      10),
        (groceries_id,     "creditor_name", "contains",    "Spar",           10),
        (transport_id,     "creditor_name", "contains",    "RET",            10),
        (transport_id,     "creditor_name", "contains",    "HTM",            10),
        (dining_id,        "creditor_name", "contains",    "Just Eat",       10),
        (dining_id,        "remittance_information", "contains", "Thuisbezorgd", 15),
    ]

    op.bulk_insert(
        rules_table,
        [
            {
                "external_id": str(uuid.uuid4()),
                "category_id": cat_id_val,
                "field": field,
                "match_type": match_type,
                "pattern": pattern,
                "is_case_sensitive": 0,
                "priority": priority,
                "is_active": 1,
                "is_system": 1,
                "hit_count": 0,
                "last_hit_at": None,
                "created_at": now,
                "updated_at": now,
            }
            for cat_id_val, field, match_type, pattern, priority in merchant_rules
        ],
    )


def downgrade() -> None:
    op.drop_table("sync_log")
    op.drop_table("sessions")
    op.drop_table("totp_secrets")
    op.drop_table("webauthn_credentials")
    op.drop_table("nordigen_tokens")
    op.drop_table("transactions")
    op.drop_table("categorization_rules")
    op.drop_table("categories")
    op.drop_table("accounts")
    op.drop_table("nordigen_requisitions")

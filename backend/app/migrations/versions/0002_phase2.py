"""Phase 2 schema — framework_type on categories + 7 new tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-01 00:00:01
"""
from __future__ import annotations

import time

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Add framework_type to categories
    # ------------------------------------------------------------------ #
    op.add_column("categories", sa.Column("framework_type", sa.Text, nullable=True))

    conn = op.get_bind()

    framework_updates = [
        ("needs",   ["Housing", "Utilities", "Healthcare", "Groceries", "Transport"]),
        ("wants",   ["Dining & Takeout", "Entertainment", "Shopping", "Subscriptions"]),
        ("savings", ["Savings"]),
        ("income",  ["Salary"]),
    ]
    for ftype, names in framework_updates:
        for name in names:
            conn.execute(
                sa.text(
                    "UPDATE categories SET framework_type = :ft WHERE name = :n"
                ),
                {"ft": ftype, "n": name},
            )

    # ------------------------------------------------------------------ #
    # budgets
    # ------------------------------------------------------------------ #
    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column(
            "category_id",
            sa.Integer,
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("monthly_amount", sa.Text, nullable=False),  # decimal as TEXT
        sa.Column("rollover_enabled", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # budget_periods
    # ------------------------------------------------------------------ #
    op.create_table(
        "budget_periods",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column(
            "budget_id",
            sa.Integer,
            sa.ForeignKey("budgets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_month", sa.Text, nullable=False),   # YYYY-MM
        sa.Column("base_amount", sa.Text, nullable=False),    # decimal as TEXT
        sa.Column("rollover_amount", sa.Text, nullable=False, server_default="0.00"),
        sa.Column("effective_amount", sa.Text, nullable=False),
        sa.Column("is_closed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
        sa.UniqueConstraint("budget_id", "period_month", name="uq_budget_period"),
    )

    # ------------------------------------------------------------------ #
    # savings_goals
    # ------------------------------------------------------------------ #
    op.create_table(
        "savings_goals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("goal_type", sa.Text, nullable=False),
        # 'emergency_fund'|'purchase'|'custom'
        sa.Column("target_amount", sa.Text, nullable=False),
        sa.Column("current_amount", sa.Text, nullable=False, server_default="0.00"),
        sa.Column("target_date", sa.Text),   # YYYY-MM-DD
        sa.Column(
            "linked_account_id",
            sa.Integer,
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("required_monthly", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column("is_active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_completed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_at", sa.Integer),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # liabilities
    # ------------------------------------------------------------------ #
    op.create_table(
        "liabilities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("liability_type", sa.Text, nullable=False),
        # 'mortgage'|'student_loan'|'personal_loan'|'credit_card'|'other'
        sa.Column("current_balance", sa.Text, nullable=False),
        sa.Column("is_active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # monthly_snapshots
    # ------------------------------------------------------------------ #
    op.create_table(
        "monthly_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("period_month", sa.Text, unique=True, nullable=False),  # YYYY-MM
        sa.Column("total_income", sa.Text, nullable=False),
        sa.Column("total_expenses", sa.Text, nullable=False),
        sa.Column("net_cash_flow", sa.Text, nullable=False),
        sa.Column("savings_rate", sa.Text, nullable=False),
        sa.Column("needs_total", sa.Text, nullable=False),
        sa.Column("wants_total", sa.Text, nullable=False),
        sa.Column("savings_total", sa.Text, nullable=False),
        sa.Column("budget_score", sa.Integer),
        sa.Column("budgets_evaluated", sa.Integer),
        sa.Column("budgets_within_limit", sa.Integer),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # net_worth_snapshots
    # ------------------------------------------------------------------ #
    op.create_table(
        "net_worth_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("snapshot_date", sa.Text, unique=True, nullable=False),  # YYYY-MM-DD
        sa.Column("total_assets", sa.Text, nullable=False),
        sa.Column("total_liabilities", sa.Text, nullable=False),
        sa.Column("net_worth", sa.Text, nullable=False),
        sa.Column("created_at", sa.Integer, nullable=False),
    )

    # ------------------------------------------------------------------ #
    # alerts
    # ------------------------------------------------------------------ #
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("external_id", sa.Text, unique=True, nullable=False),
        sa.Column("alert_type", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column(
            "related_transaction_id",
            sa.Integer,
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "related_budget_id",
            sa.Integer,
            sa.ForeignKey("budgets.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "related_goal_id",
            sa.Integer,
            sa.ForeignKey("savings_goals.id", ondelete="SET NULL"),
        ),
        sa.Column("is_read", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_dismissed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Integer, nullable=False),
        sa.Column("expires_at", sa.Integer),
    )


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("net_worth_snapshots")
    op.drop_table("monthly_snapshots")
    op.drop_table("liabilities")
    op.drop_table("savings_goals")
    op.drop_table("budget_periods")
    op.drop_table("budgets")
    op.drop_column("categories", "framework_type")

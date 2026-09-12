"""Liability service — Phase 2 Module 3.

Tracks debts (mortgage, loans, credit cards) for net worth calculation.
"""
from __future__ import annotations

import time
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy.orm import Session


def _dec(value: str | None) -> Decimal:
    try:
        return Decimal(value or "0")
    except InvalidOperation:
        return Decimal("0")


def list_liabilities(db: Session) -> list[dict]:
    """Return all active liabilities."""
    from app.models.liabilities import Liability

    rows = (
        db.query(Liability)
        .filter(Liability.is_active == 1)
        .order_by(Liability.created_at.asc())
        .all()
    )
    return [
        {
            "external_id": r.external_id,
            "name": r.name,
            "liability_type": r.liability_type,
            "current_balance": r.current_balance,
            "created_at": r.created_at,
        }
        for r in rows
    ]


def create_liability(
    db: Session,
    name: str,
    liability_type: str,
    current_balance: Decimal,
) -> dict:
    """Create a new liability entry."""
    from app.models.liabilities import Liability

    now = int(time.time())
    balance_str = str(current_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    lib = Liability(
        external_id=str(uuid.uuid4()),
        name=name,
        liability_type=liability_type,
        current_balance=balance_str,
        is_active=1,
        created_at=now,
        updated_at=now,
    )
    db.add(lib)
    db.commit()
    db.refresh(lib)
    return {
        "external_id": lib.external_id,
        "name": lib.name,
        "liability_type": lib.liability_type,
        "current_balance": lib.current_balance,
        "created_at": lib.created_at,
    }


def update_liability_balance(
    db: Session,
    external_id: str,
    new_balance: Decimal,
) -> dict | None:
    """Update the current balance of a liability."""
    from app.models.liabilities import Liability

    lib = (
        db.query(Liability)
        .filter(Liability.external_id == external_id, Liability.is_active == 1)
        .first()
    )
    if not lib:
        return None

    lib.current_balance = str(new_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    lib.updated_at = int(time.time())
    db.commit()
    db.refresh(lib)
    return {
        "external_id": lib.external_id,
        "name": lib.name,
        "liability_type": lib.liability_type,
        "current_balance": lib.current_balance,
        "created_at": lib.created_at,
    }


def delete_liability(db: Session, external_id: str) -> bool:
    """Soft-delete a liability. Returns True if found and deleted."""
    from app.models.liabilities import Liability

    lib = (
        db.query(Liability)
        .filter(Liability.external_id == external_id, Liability.is_active == 1)
        .first()
    )
    if not lib:
        return False
    lib.is_active = 0
    lib.updated_at = int(time.time())
    db.commit()
    return True


def total_liabilities(db: Session) -> Decimal:
    """Return the sum of all active liability balances."""
    from app.models.liabilities import Liability

    rows = db.query(Liability).filter(Liability.is_active == 1).all()
    return sum((_dec(r.current_balance) for r in rows), Decimal("0"))

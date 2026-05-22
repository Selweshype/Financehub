"""Nordigen transaction sync service.

Fetches transactions from GoCardless for all linked accounts and imports
them into the local database, running the categorizer on each new transaction.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import get_secrets
from app.database import get_db
from app.services.categorizer import categorize
from app.services.nordigen_client import NordigenClient
from app.services.token_store import NordigenTokenStore


@dataclass
class SyncResult:
    """Result of a sync operation for one or all accounts."""

    account_id: int | None = None
    transactions_added: int = 0
    status: str = "success"
    error_message: str | None = None
    errors: list[str] = field(default_factory=list)


async def _get_valid_access_token(
    db: Session, client: NordigenClient
) -> str:
    """Return a valid Nordigen access token, refreshing/re-obtaining as needed."""
    store = NordigenTokenStore(db)
    token_data = store.load()

    kwargs: dict = {}
    if token_data:
        kwargs = {
            "access_token": token_data["access_token"],
            "access_expires_at": token_data["access_expires_at"],
            "refresh_token": token_data["refresh_token"],
            "refresh_expires_at": token_data["refresh_expires_at"],
        }

    new_tokens = await client.ensure_token(**kwargs)
    store.save(
        access_token=new_tokens["access"],
        access_expires_at=int(time.time()) + new_tokens["access_expires"],
        refresh_token=new_tokens["refresh"],
        refresh_expires_at=int(time.time()) + new_tokens["refresh_expires"],
    )
    return new_tokens["access"]


async def sync_account(
    db: Session,
    account,  # Account ORM row
    client: NordigenClient,
    access_token: str,
) -> SyncResult:
    """Sync a single account and return a SyncResult."""
    from app.models.accounts import Account
    from app.models.nordigen import SyncLog
    from app.models.transactions import Transaction

    result = SyncResult(account_id=account.id)
    now = int(time.time())

    try:
        raw = await client.get_account_transactions(
            access_token, account.nordigen_account_id
        )
        booked = raw.get("transactions", {}).get("booked", [])
        pending = raw.get("transactions", {}).get("pending", [])

        all_txs = [(t, False) for t in booked] + [(t, True) for t in pending]

        for tx_data, is_pending in all_txs:
            nordigen_tx_id = tx_data.get("transactionId") or tx_data.get(
                "internalTransactionId"
            )

            # Dedup by Nordigen transaction ID
            if nordigen_tx_id:
                exists = (
                    db.query(Transaction)
                    .filter(Transaction.nordigen_transaction_id == nordigen_tx_id)
                    .first()
                )
                if exists:
                    continue

            amount_data = tx_data.get("transactionAmount", {})
            amount_str = str(amount_data.get("amount", "0"))
            currency = amount_data.get("currency", "EUR")

            tx = Transaction(
                external_id=str(uuid.uuid4()),
                account_id=account.id,
                nordigen_transaction_id=nordigen_tx_id,
                booking_date=tx_data.get("bookingDate"),
                value_date=tx_data.get("valueDate"),
                amount=amount_str,
                currency=currency,
                creditor_name=tx_data.get("creditorName"),
                debtor_name=tx_data.get("debtorName"),
                remittance_information=tx_data.get("remittanceInformationUnstructured"),
                proprietary_bank_code=tx_data.get("proprietaryBankTransactionCode"),
                is_pending=1 if is_pending else 0,
                imported_at=now,
                created_at=now,
                updated_at=now,
            )

            # Auto-categorize
            cat_id, rule_id = categorize(tx, db)
            if cat_id:
                tx.category_id = cat_id
                tx.categorization_rule_id = rule_id
                tx.categorization_source = "rule"

            db.add(tx)
            result.transactions_added += 1

        # Update account balance
        try:
            balances_raw = await client.get_account_balances(
                access_token, account.nordigen_account_id
            )
            balances = balances_raw.get("balances", [])
            if balances:
                first_balance = balances[0]
                bal_amount = first_balance.get("balanceAmount", {})
                account.balance_amount = str(bal_amount.get("amount", "0"))
                account.balance_type = first_balance.get("balanceType")
                account.balance_updated_at = now
        except Exception:
            pass  # Balance update failure is non-fatal

        db.commit()

    except Exception as exc:
        db.rollback()
        result.status = "error"
        result.error_message = str(exc)

    # Write sync log
    log = SyncLog(
        account_id=account.id,
        synced_at=now,
        status=result.status,
        error_message=result.error_message,
        transactions_added=result.transactions_added,
    )
    db.add(log)
    try:
        db.commit()
    except Exception:
        db.rollback()

    return result


async def sync_all() -> list[SyncResult]:
    """Sync all active accounts. Called by the scheduler."""
    from app.models.accounts import Account

    secrets = get_secrets()
    client = NordigenClient(
        secret_id=secrets.nordigen.secret_id,
        secret_key=secrets.nordigen.secret_key,
    )

    results: list[SyncResult] = []
    db_gen = get_db()
    db: Session = next(db_gen)

    try:
        access_token = await _get_valid_access_token(db, client)
        accounts = db.query(Account).filter(Account.is_active == 1).all()

        for account in accounts:
            if not account.nordigen_account_id:
                continue
            result = await sync_account(db, account, client, access_token)
            results.append(result)
    except Exception as exc:
        from app.models.nordigen import SyncLog
        now = int(time.time())
        log = SyncLog(
            account_id=None,
            synced_at=now,
            status="error",
            error_message=str(exc),
            transactions_added=0,
        )
        db.add(log)
        try:
            db.commit()
        except Exception:
            db.rollback()
        results.append(SyncResult(status="error", error_message=str(exc)))
    finally:
        db.close()
        await client.aclose()

    return results

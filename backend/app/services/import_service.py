"""CSV import for Dutch bank exports (ING and BUNQ).

Until now the only way to get a transaction into the database was a live
GoCardless sync, which needs an API account and a public HTTPS redirect URL.
This module makes the app usable from a downloaded bank export instead, and
stays useful afterwards as a fallback whenever a bank link breaks.

Design notes
------------
*No schema migration is required.* Two existing columns carry the weight:

- ``Account.nordigen_account_id`` is nullable, so an imported account is just a
  normal Account row with that column left NULL.
- ``Transaction.nordigen_transaction_id`` is a nullable UNIQUE column that
  ``sync_service`` already de-duplicates on. Writing a deterministic synthetic
  key there (``csv:<hash>``) makes re-importing the same file — or two exports
  with an overlapping date range — idempotent for free.

*Unknown formats are rejected, never guessed at.* Bank exports change their
column headers between years and between personal/business accounts. Silently
mis-mapping a column would corrupt the ledger in a way nobody would notice, so
an unrecognised header raises with the headers it actually saw.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.money import to_decimal

logger = logging.getLogger(__name__)

# Guard against a huge or malicious upload being read into memory.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ROWS = 50_000


class ImportError_(Exception):
    """Raised when a file cannot be imported at all (as opposed to a bad row)."""


@dataclass
class RowError:
    line: int
    reason: str
    raw: str = ""


@dataclass
class ImportResult:
    bank: str = ""
    account_external_id: str | None = None
    imported: int = 0
    duplicates: int = 0
    rejected: list[RowError] = field(default_factory=list)
    categorized: int = 0

    @property
    def total_rows(self) -> int:
        return self.imported + self.duplicates + len(self.rejected)


# --------------------------------------------------------------------------- #
# Format profiles
# --------------------------------------------------------------------------- #
#
# Each profile declares the headers that identify the format and how to read one
# row. `required` headers must ALL be present for the profile to match.

def _parse_date(value: str, formats: tuple[str, ...]) -> str:
    """Return an ISO YYYY-MM-DD date string, or raise ValueError."""
    text = (value or "").strip()
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def _parse_dutch_amount(value: str) -> Decimal:
    """Parse an amount that may use ',' as the decimal separator.

    ING writes ``1.234,56``; BUNQ writes ``1234.56``. Both appear with and
    without a thousands separator depending on locale settings at export time.
    """
    text = (value or "").strip().replace(" ", "").replace(" ", "")
    if not text:
        raise ValueError("empty amount")

    if "," in text and "." in text:
        # Whichever comes last is the decimal separator.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"unrecognised amount {value!r}") from exc


def _ing_row(row: dict[str, str]) -> dict:
    """Map one ING export row.

    ING stores the amount unsigned and puts the direction in a separate
    ``Af Bij`` column ("Af" = debit). Applying that sign is essential: without
    it every expense would be imported as income.
    """
    amount = _parse_dutch_amount(row.get("Bedrag (EUR)", ""))
    direction = (row.get("Af Bij") or "").strip().lower()
    if direction in {"af", "debit"}:
        amount = -abs(amount)
    elif direction in {"bij", "credit"}:
        amount = abs(amount)
    else:
        raise ValueError(f"unrecognised Af Bij value {row.get('Af Bij')!r}")

    counterparty = (row.get("Naam / Omschrijving") or "").strip()
    description = (row.get("Mededelingen") or "").strip()

    return {
        "booking_date": _parse_date(row.get("Datum", ""), ("%Y%m%d", "%d-%m-%Y", "%Y-%m-%d")),
        "amount": amount,
        "counterparty": counterparty,
        "description": description,
        "code": (row.get("Code") or "").strip() or None,
        "counterparty_iban": (row.get("Tegenrekening") or "").strip() or None,
        "own_account": (row.get("Rekening") or "").strip() or None,
    }


def _bunq_row(row: dict[str, str]) -> dict:
    """Map one BUNQ export row. BUNQ amounts are already signed."""
    amount = _parse_dutch_amount(row.get("Amount", ""))
    counterparty = (row.get("Counterparty") or row.get("Name") or "").strip()

    return {
        "booking_date": _parse_date(row.get("Date", ""), ("%Y-%m-%d", "%d-%m-%Y")),
        "amount": amount,
        "counterparty": counterparty,
        "description": (row.get("Description") or "").strip(),
        "code": None,
        "counterparty_iban": (row.get("Counterparty") or "").strip() or None,
        "own_account": (row.get("Account") or "").strip() or None,
    }


PROFILES: dict[str, dict] = {
    "ING": {
        "required": {"Datum", "Bedrag (EUR)", "Af Bij"},
        "parse": _ing_row,
        "bank_name": "ING",
    },
    "BUNQ": {
        "required": {"Date", "Amount"},
        "parse": _bunq_row,
        "bank_name": "bunq",
    },
}


def detect_profile(headers: list[str]) -> str:
    """Return the profile name matching *headers*, or raise ImportError_.

    Fails closed on purpose — see the module docstring.
    """
    present = {h.strip() for h in headers if h}
    for name, profile in PROFILES.items():
        if profile["required"] <= present:
            return name

    raise ImportError_(
        "Unrecognised CSV format. Expected an ING export (columns including "
        "'Datum', 'Bedrag (EUR)', 'Af Bij') or a BUNQ export (columns including "
        f"'Date', 'Amount'). Found: {sorted(present)}"
    )


# --------------------------------------------------------------------------- #
# Dedup key
# --------------------------------------------------------------------------- #

def build_dedup_key(account_id: int, parsed: dict) -> str:
    """Deterministic id for a CSV row, stored in nordigen_transaction_id.

    Reuses the UNIQUE constraint sync_service already relies on, so importing
    the same export twice is a no-op and overlapping date ranges merge cleanly.
    Two genuinely identical transactions on the same day (say, two identical
    coffees) collapse into one — an accepted trade-off, since bank exports
    carry no per-row identifier to distinguish them.
    """
    fingerprint = "|".join(
        [
            str(account_id),
            parsed["booking_date"],
            str(parsed["amount"]),
            parsed["counterparty"],
            parsed["description"],
        ]
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:40]
    return f"csv:{digest}"


# --------------------------------------------------------------------------- #
# Account
# --------------------------------------------------------------------------- #

def get_or_create_import_account(db: Session, bank_name: str, label: str | None = None):
    """Return the Account that imported rows attach to, creating it if needed.

    Transaction.account_id is NOT NULL, so an import needs an Account. This is
    an ordinary row with nordigen_account_id left NULL, which is what
    distinguishes it from a bank-linked account.
    """
    from app.models.accounts import Account

    account_name = label or f"{bank_name} (imported)"

    existing = (
        db.query(Account)
        .filter(
            Account.nordigen_account_id.is_(None),
            Account.account_name == account_name,
        )
        .first()
    )
    if existing:
        return existing

    now = int(time.time())
    account = Account(
        external_id=str(uuid.uuid4()),
        nordigen_account_id=None,
        bank_name=bank_name,
        account_name=account_name,
        currency="EUR",
        is_active=1,
        created_at=now,
        updated_at=now,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #

def _decode(raw: bytes) -> str:
    """Decode an export, tolerating the encodings Dutch banks actually emit."""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportError_("Could not decode the file as text.")


def import_csv(
    db: Session,
    raw: bytes,
    account_label: str | None = None,
) -> ImportResult:
    """Import a bank CSV export. Idempotent: re-importing inserts nothing new."""
    from app.models.transactions import Transaction
    from app.services.categorizer import categorize

    if not raw:
        raise ImportError_("The uploaded file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImportError_(
            f"File is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit."
        )

    text = _decode(raw)

    # Bank exports use ',' or ';' depending on locale.
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ImportError_("The file has no header row.")

    profile_name = detect_profile(list(reader.fieldnames))
    profile = PROFILES[profile_name]
    parse_row = profile["parse"]

    account = get_or_create_import_account(db, profile["bank_name"], account_label)
    result = ImportResult(bank=profile_name, account_external_id=account.external_id)

    now = int(time.time())
    seen_in_file: set[str] = set()
    pending: list[Transaction] = []

    for line_number, row in enumerate(reader, start=2):  # line 1 is the header
        if result.total_rows >= MAX_ROWS:
            raise ImportError_(f"File exceeds the {MAX_ROWS:,}-row limit.")

        try:
            parsed = parse_row(row)
        except ValueError as exc:
            result.rejected.append(RowError(line=line_number, reason=str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - one bad row must not kill the import
            logger.warning("Unexpected error parsing CSV line %d", line_number, exc_info=True)
            result.rejected.append(RowError(line=line_number, reason=f"unreadable row: {exc}"))
            continue

        dedup_key = build_dedup_key(account.id, parsed)

        # Duplicate within this same file (some exports repeat rows).
        if dedup_key in seen_in_file:
            result.duplicates += 1
            continue
        seen_in_file.add(dedup_key)

        already = (
            db.query(Transaction.id)
            .filter(Transaction.nordigen_transaction_id == dedup_key)
            .first()
        )
        if already:
            result.duplicates += 1
            continue

        amount: Decimal = parsed["amount"]
        # Expenses are negative; the counterparty is a creditor when money goes
        # out and a debtor when it comes in. The categorizer matches on both.
        is_outgoing = amount < 0

        tx = Transaction(
            external_id=str(uuid.uuid4()),
            account_id=account.id,
            nordigen_transaction_id=dedup_key,
            booking_date=parsed["booking_date"],
            value_date=parsed["booking_date"],
            amount=str(amount),
            currency="EUR",
            creditor_name=parsed["counterparty"] if is_outgoing else None,
            debtor_name=None if is_outgoing else parsed["counterparty"],
            remittance_information=parsed["description"] or None,
            proprietary_bank_code=parsed["code"],
            is_pending=0,
            imported_at=now,
            created_at=now,
            updated_at=now,
        )

        category_id, rule_id = categorize(tx, db)
        if category_id:
            tx.category_id = category_id
            tx.categorization_rule_id = rule_id
            tx.categorization_source = "rule"
            result.categorized += 1

        db.add(tx)
        pending.append(tx)
        result.imported += 1

    if pending:
        db.commit()

    logger.info(
        "CSV import (%s): %d imported, %d duplicate, %d rejected, %d auto-categorized",
        profile_name,
        result.imported,
        result.duplicates,
        len(result.rejected),
        result.categorized,
    )
    return result


def account_balance_from_transactions(db: Session, account_id: int) -> Decimal:
    """Sum an imported account's transactions.

    A CSV export carries no authoritative balance, so an imported account's
    balance is derived from its rows. Folded with Decimal — never SQL SUM().
    """
    from app.models.transactions import Transaction

    rows = (
        db.query(Transaction.amount)
        .filter(Transaction.account_id == account_id, Transaction.is_pending == 0)
        .all()
    )
    total = Decimal("0")
    for (amount,) in rows:
        total += to_decimal(amount, default="0")
    return total

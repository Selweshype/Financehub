"""Transaction categorization engine.

Rules are loaded from the database and cached in-process for 5 minutes.
Supports four match types: exact, contains, starts_with, regex.
The rule with the lowest *priority* number wins when multiple rules match.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models.transactions import Transaction

_CACHE_TTL = 300  # 5 minutes


@dataclass
class _RuleCache:
    rules: list[dict]
    loaded_at: float = field(default_factory=time.monotonic)

    def is_stale(self) -> bool:
        return time.monotonic() - self.loaded_at > _CACHE_TTL


_cache: _RuleCache | None = None


def _load_rules(db: Session) -> list[dict]:
    """Load active rules from DB, ordered by priority ascending."""
    from app.models.categories import CategorizationRule

    rows = (
        db.query(CategorizationRule)
        .filter(CategorizationRule.is_active == 1)
        .order_by(CategorizationRule.priority.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "category_id": r.category_id,
            "field": r.field,
            "match_type": r.match_type,
            "pattern": r.pattern,
            "is_case_sensitive": bool(r.is_case_sensitive),
        }
        for r in rows
    ]


def _get_rules(db: Session) -> list[dict]:
    """Return cached rules, refreshing if stale."""
    global _cache
    if _cache is None or _cache.is_stale():
        _cache = _RuleCache(rules=_load_rules(db))
    return _cache.rules


def invalidate_cache() -> None:
    """Force rules to be reloaded on the next categorization call."""
    global _cache
    _cache = None


def _field_value(transaction_data: dict, field_name: str) -> str:
    """Extract a string value from the transaction dict for a given field."""
    return str(transaction_data.get(field_name) or "")


def _matches(value: str, match_type: str, pattern: str, case_sensitive: bool) -> bool:
    """Return True if *value* matches *pattern* using *match_type*."""
    if not case_sensitive:
        value = value.lower()
        pattern_cmp = pattern.lower()
    else:
        pattern_cmp = pattern

    if match_type == "exact":
        return value == pattern_cmp
    elif match_type == "contains":
        return pattern_cmp in value
    elif match_type == "starts_with":
        return value.startswith(pattern_cmp)
    elif match_type == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return bool(re.search(pattern, value, flags))
        except re.error:
            return False
    return False


def categorize(
    transaction: "Transaction",
    db: Session,
) -> tuple[int | None, int | None]:
    """Attempt to categorize *transaction* using the rule engine.

    Returns ``(category_id, rule_id)`` if a rule matches, ``(None, None)`` otherwise.
    Updates rule hit statistics when a match is found.
    """
    rules = _get_rules(db)

    tx_data = {
        "creditor_name": transaction.creditor_name,
        "debtor_name": transaction.debtor_name,
        "remittance_information": transaction.remittance_information,
        "proprietary_bank_code": transaction.proprietary_bank_code,
    }

    for rule in rules:
        value = _field_value(tx_data, rule["field"])
        if _matches(value, rule["match_type"], rule["pattern"], rule["is_case_sensitive"]):
            # Update hit statistics (best effort, non-fatal)
            try:
                from app.models.categories import CategorizationRule

                db_rule = db.get(CategorizationRule, rule["id"])
                if db_rule:
                    db_rule.hit_count = (db_rule.hit_count or 0) + 1
                    db_rule.last_hit_at = int(time.time())
                    db.commit()
            except Exception:
                db.rollback()

            return rule["category_id"], rule["id"]

    return None, None

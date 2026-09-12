"""Tests for CSV import.

The cases that matter most: sign normalization (getting this wrong turns every
expense into income) and dedup idempotency (re-importing an overlapping export
must not double-count).
"""

from decimal import Decimal

import pytest

from app.services import import_service
from app.services.import_service import ImportError_, import_csv

# --------------------------------------------------------------------------- #
# Sample exports
# --------------------------------------------------------------------------- #

ING_CSV = (
    '"Datum","Naam / Omschrijving","Rekening","Tegenrekening","Code","Af Bij",'
    '"Bedrag (EUR)","Mutatiesoort","Mededelingen"\r\n'
    '"20260304","Albert Heijn 1234","NL01INGB0001234567","","BA","Af",'
    '"25,50","Betaalautomaat","Pasvolgnr 001"\r\n'
    '"20260305","Salaris Werkgever BV","NL01INGB0001234567","NL99BANK0000000001","OV","Bij",'
    '"2.500,00","Overschrijving","Salaris maart"\r\n'
    '"20260306","Albert Heijn 1234","NL01INGB0001234567","","BA","Af",'
    '"10,25","Betaalautomaat","Pasvolgnr 002"\r\n'
)

BUNQ_CSV = (
    '"Date","Amount","Account","Counterparty","Name","Description"\r\n'
    '"2026-03-04","-25.50","NL01BUNQ0001234567","NL22ABNA0123456789","Albert Heijn","Groceries"\r\n'
    '"2026-03-05","2500.00","NL01BUNQ0001234567","NL99BANK0000000001","Werkgever BV","Salaris"\r\n'
)


class TestFormatDetection:
    def test_detects_ing(self):
        assert import_service.detect_profile(
            ["Datum", "Naam / Omschrijving", "Bedrag (EUR)", "Af Bij"]
        ) == "ING"

    def test_detects_bunq(self):
        assert import_service.detect_profile(
            ["Date", "Amount", "Account", "Counterparty"]
        ) == "BUNQ"

    def test_unknown_format_is_rejected_not_guessed(self):
        """Silently mis-mapping columns would corrupt the ledger invisibly."""
        with pytest.raises(ImportError_, match="Unrecognised CSV format"):
            import_service.detect_profile(["Transaction Date", "Debit", "Credit"])

    def test_rejection_names_the_headers_it_saw(self):
        with pytest.raises(ImportError_, match="Wibble"):
            import_service.detect_profile(["Wibble", "Wobble"])


class TestAmountParsing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("25,50", Decimal("25.50")),       # Dutch decimal comma
            ("1.234,56", Decimal("1234.56")),  # Dutch thousands + decimal
            ("1234.56", Decimal("1234.56")),   # plain
            ("2,500.00", Decimal("2500.00")),  # English thousands + decimal
            ("-12,30", Decimal("-12.30")),
            ("0,00", Decimal("0.00")),
        ],
    )
    def test_parses_locale_variants(self, raw, expected):
        assert import_service._parse_dutch_amount(raw) == expected

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty amount"):
            import_service._parse_dutch_amount("")

    def test_rejects_garbage(self):
        with pytest.raises(ValueError, match="unrecognised amount"):
            import_service._parse_dutch_amount("twelve euro")


class TestIngImport:
    def test_applies_af_bij_sign(self, db):
        """ING amounts are unsigned; the direction lives in 'Af Bij'.

        Without applying it every expense would import as income.
        """
        result = import_csv(db, ING_CSV.encode())
        assert result.imported == 3

        from app.models.transactions import Transaction

        by_date = {t.booking_date: t for t in db.query(Transaction).all()}
        assert Decimal(by_date["2026-03-04"].amount) == Decimal("-25.50")  # Af
        assert Decimal(by_date["2026-03-05"].amount) == Decimal("2500.00")  # Bij
        assert Decimal(by_date["2026-03-06"].amount) == Decimal("-10.25")  # Af

    def test_parses_yyyymmdd_dates(self, db):
        import_csv(db, ING_CSV.encode())
        from app.models.transactions import Transaction

        dates = sorted(t.booking_date for t in db.query(Transaction).all())
        assert dates == ["2026-03-04", "2026-03-05", "2026-03-06"]

    def test_counterparty_side_follows_direction(self, db):
        import_csv(db, ING_CSV.encode())
        from app.models.transactions import Transaction

        outgoing = (
            db.query(Transaction).filter(Transaction.booking_date == "2026-03-04").one()
        )
        incoming = (
            db.query(Transaction).filter(Transaction.booking_date == "2026-03-05").one()
        )
        assert outgoing.creditor_name == "Albert Heijn 1234"
        assert outgoing.debtor_name is None
        assert incoming.debtor_name == "Salaris Werkgever BV"
        assert incoming.creditor_name is None

    def test_rejects_unknown_af_bij_value(self, db):
        bad = ING_CSV.replace('"Af"', '"Sideways"', 1)
        result = import_csv(db, bad.encode())

        assert result.imported == 2
        assert len(result.rejected) == 1
        assert "Af Bij" in result.rejected[0].reason


class TestBunqImport:
    def test_imports_signed_amounts_unchanged(self, db):
        result = import_csv(db, BUNQ_CSV.encode())
        assert result.imported == 2

        from app.models.transactions import Transaction

        amounts = sorted(Decimal(t.amount) for t in db.query(Transaction).all())
        assert amounts == [Decimal("-25.50"), Decimal("2500.00")]

    def test_creates_a_separate_account_per_bank(self, db):
        import_csv(db, ING_CSV.encode())
        import_csv(db, BUNQ_CSV.encode())

        from app.models.accounts import Account

        names = sorted(a.bank_name for a in db.query(Account).all())
        assert names == ["ING", "bunq"]


class TestIdempotency:
    def test_reimporting_the_same_file_adds_nothing(self, db):
        first = import_csv(db, ING_CSV.encode())
        second = import_csv(db, ING_CSV.encode())

        assert first.imported == 3
        assert second.imported == 0
        assert second.duplicates == 3

        from app.models.transactions import Transaction

        assert db.query(Transaction).count() == 3

    def test_overlapping_exports_merge_without_double_counting(self, db):
        """Monthly exports usually overlap by a few days."""
        header, *rows = ING_CSV.strip().split("\r\n")
        first_file = "\r\n".join([header, rows[0], rows[1]]) + "\r\n"
        overlapping = "\r\n".join([header, rows[1], rows[2]]) + "\r\n"

        import_csv(db, first_file.encode())
        second = import_csv(db, overlapping.encode())

        from app.models.transactions import Transaction

        assert second.imported == 1, "only the genuinely new row"
        assert second.duplicates == 1, "the overlapping row"
        assert db.query(Transaction).count() == 3

    def test_duplicate_rows_within_one_file_collapse(self, db):
        header, *rows = ING_CSV.strip().split("\r\n")
        doubled = "\r\n".join([header, rows[0], rows[0]]) + "\r\n"

        result = import_csv(db, doubled.encode())

        assert result.imported == 1
        assert result.duplicates == 1

    def test_dedup_key_is_stable_and_scoped_to_account(self):
        parsed = {
            "booking_date": "2026-03-04",
            "amount": Decimal("-25.50"),
            "counterparty": "Albert Heijn",
            "description": "Groceries",
        }
        assert import_service.build_dedup_key(1, parsed) == import_service.build_dedup_key(
            1, parsed
        )
        assert import_service.build_dedup_key(1, parsed) != import_service.build_dedup_key(
            2, parsed
        )


class TestCategorization:
    def test_applies_seeded_rules(self, db, make_category):
        """Imported rows run through the same rule engine as synced rows."""
        import time
        import uuid as _uuid

        from app.models.categories import CategorizationRule
        from app.services.categorizer import invalidate_cache

        groceries = make_category("Groceries", "needs")
        db.add(
            CategorizationRule(
                external_id=str(_uuid.uuid4()),
                category_id=groceries.id,
                field="creditor_name",
                match_type="contains",
                pattern="Albert Heijn",
                is_case_sensitive=0,
                priority=10,
                is_active=1,
                created_at=int(time.time()),
                updated_at=int(time.time()),
            )
        )
        db.commit()
        invalidate_cache()

        result = import_csv(db, ING_CSV.encode())

        assert result.categorized == 2
        from app.models.transactions import Transaction

        tx = db.query(Transaction).filter(Transaction.booking_date == "2026-03-04").one()
        assert tx.category_id == groceries.id
        assert tx.categorization_source == "rule"


class TestFileLevelFailures:
    def test_empty_file(self, db):
        with pytest.raises(ImportError_, match="empty"):
            import_csv(db, b"")

    def test_header_only_imports_nothing(self, db):
        header = ING_CSV.split("\r\n")[0] + "\r\n"
        result = import_csv(db, header.encode())
        assert result.imported == 0
        assert result.rejected == []

    def test_oversized_file_rejected(self, db):
        with pytest.raises(ImportError_, match="larger than"):
            import_csv(db, b"x" * (import_service.MAX_UPLOAD_BYTES + 1))

    def test_semicolon_delimited_export(self, db):
        """Dutch locale exports often use ';' as the field separator."""
        semi = (
            '"Datum";"Naam / Omschrijving";"Rekening";"Tegenrekening";"Code";'
            '"Af Bij";"Bedrag (EUR)";"Mutatiesoort";"Mededelingen"\r\n'
            '"20260304";"Albert Heijn 1234";"NL01INGB0001234567";"";"BA";'
            '"Af";"25,50";"Betaalautomaat";"Pasvolgnr 001"\r\n'
            '"20260305";"Salaris Werkgever BV";"NL01INGB0001234567";"";"OV";'
            '"Bij";"2.500,00";"Overschrijving";"Salaris maart"\r\n'
        )
        result = import_csv(db, semi.encode())

        assert result.imported == 2
        from app.models.transactions import Transaction

        amounts = sorted(Decimal(t.amount) for t in db.query(Transaction).all())
        assert amounts == [Decimal("-25.50"), Decimal("2500.00")]

    def test_cp1252_encoded_file(self, db):
        """Older ING exports are not UTF-8."""
        content = ING_CSV.replace("Albert Heijn 1234", "Café Zürich")
        result = import_csv(db, content.encode("cp1252"))
        assert result.imported == 3

        from app.models.transactions import Transaction

        tx = db.query(Transaction).filter(Transaction.booking_date == "2026-03-04").one()
        assert tx.creditor_name == "Café Zürich"


class TestDerivedBalance:
    def test_balance_is_the_exact_decimal_sum(self, db):
        import_csv(db, ING_CSV.encode())

        from app.models.accounts import Account

        account = db.query(Account).one()
        balance = import_service.account_balance_from_transactions(db, account.id)

        # 2500.00 - 25.50 - 10.25
        assert balance == Decimal("2464.25")

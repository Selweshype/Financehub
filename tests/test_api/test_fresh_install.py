"""Regressions for crashes that only appear on a brand-new, empty install.

These were found while verifying the security work end to end: the app had
never actually been started before, so several paths that only run against an
empty database had never executed.

The `compute_remaining_today` cases that used to live here were weak — they
mocked out `get_budget_summary` and then asserted only `> 0`, which almost any
implementation satisfies. They are replaced by exact-value tests against a real
database in tests/test_services/test_budget_service.py.
"""

import os
from unittest.mock import patch

import pytest


def test_empty_db_key_refuses_to_open_database():
    """An unset key silently produced a *plaintext* SQLite file."""
    from app.database import _apply_pragmas

    class FakeConn:
        def __init__(self):
            self.statements = []

        def execute(self, sql):
            self.statements.append(sql)

    conn = FakeConn()
    with patch.dict(os.environ, {"FINANCEHUB_DB_KEY": ""}, clear=False):
        with pytest.raises(ValueError, match="unencrypted"):
            _apply_pragmas(conn, None)

    assert conn.statements == [], "nothing may be written without an encryption key"


def test_index_renders_empty_state_when_the_query_layer_fails():
    """`date` was imported inside the try block but used after it.

    Any failure in the dashboard query path therefore raised UnboundLocalError
    instead of falling back to the empty state the except clause intends.

    This drives the actual failure rather than inspecting the source text, so
    it keeps working if the code is reorganised.
    """
    import asyncio
    import types

    import app.main as main_module

    captured = {}

    class FakeTemplates:
        def TemplateResponse(self, name, context):
            captured["name"] = name
            captured["context"] = context
            return "rendered"

    class ExplodingSession:
        def query(self, *_args, **_kwargs):
            raise RuntimeError("database is unavailable")

        def close(self):
            pass

    def exploding_get_db():
        yield ExplodingSession()

    request = types.SimpleNamespace(state=types.SimpleNamespace(csp_nonce="test-nonce"))

    with patch.object(main_module, "templates", FakeTemplates()), patch(
        "app.database.get_db", exploding_get_db
    ):
        result = asyncio.run(main_module.index(request))

    assert result == "rendered", "the dashboard must still render, not raise"
    assert captured["name"] == "dashboard/index.html"
    # Degrades to the empty state rather than blowing up.
    assert captured["context"]["account_count"] == 0
    assert captured["context"]["transaction_count"] == 0
    # current_month must still be populated — this is the value that was unbound.
    assert captured["context"]["current_month"]

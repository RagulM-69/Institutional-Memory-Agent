"""
Unit tests validating database connection pooling, transaction context,
and RLS session variable scoping.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from apps.api.db.pool import transaction_context


class MockAsyncpgConnection:
    """Mock asyncpg.Connection tracking execute calls and transaction lifecycle."""
    def __init__(self):
        self.executed_queries: list[tuple[str, tuple]] = []
        self.transaction_active = False
        self.committed = False
        self.rolled_back = False

    @asynccontextmanager
    async def transaction(self):
        self.transaction_active = True
        try:
            yield self
            self.committed = True
        except Exception:
            self.rolled_back = True
            raise
        finally:
            self.transaction_active = False

    async def execute(self, query: str, *args):
        self.executed_queries.append((query, args))


@pytest.mark.asyncio
async def test_transaction_context_sets_local_variables():
    user_id = uuid4()
    org_id = uuid4()
    mock_conn = MockAsyncpgConnection()

    async with transaction_context(user_id=user_id, org_id=org_id, connection=mock_conn) as conn:
        assert conn is mock_conn
        # Inside context, transaction must be active
        assert mock_conn.transaction_active is True

    # After exit, transaction must be committed
    assert mock_conn.committed is True
    assert mock_conn.rolled_back is False
    assert mock_conn.transaction_active is False

    # Check queries executed: must use is_local=true (third argument in set_config)
    queries = [q for q, _ in mock_conn.executed_queries]
    args = [a for _, a in mock_conn.executed_queries]

    assert any("set_config('app.current_user_id', $1, true)" in q for q in queries)
    assert any("set_config('app.current_org_id', $1, true)" in q for q in queries)

    # Check parameter bindings
    bound_args = [a[0] for a in args if len(a) > 0]
    assert str(user_id) in bound_args
    assert str(org_id) in bound_args


@pytest.mark.asyncio
async def test_transaction_context_rolls_back_on_error():
    user_id = uuid4()
    org_id = uuid4()
    mock_conn = MockAsyncpgConnection()

    with pytest.raises(ValueError, match="Simulated application error"):
        async with transaction_context(user_id=user_id, org_id=org_id, connection=mock_conn):
            raise ValueError("Simulated application error")

    assert mock_conn.committed is False
    assert mock_conn.rolled_back is True
    assert mock_conn.transaction_active is False


@pytest.mark.asyncio
async def test_transaction_context_from_pool(monkeypatch):
    user_id = uuid4()
    org_id = uuid4()
    mock_conn = MockAsyncpgConnection()

    @asynccontextmanager
    async def fake_get_connection():
        yield mock_conn

    monkeypatch.setattr("apps.api.db.pool.get_connection", fake_get_connection)

    async with transaction_context(user_id=user_id, org_id=org_id) as conn:
        assert conn is mock_conn
        assert mock_conn.transaction_active is True

    assert mock_conn.committed is True
    assert mock_conn.rolled_back is False


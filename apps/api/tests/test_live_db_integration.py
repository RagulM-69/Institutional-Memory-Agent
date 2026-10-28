"""
Live integration test executing against Supabase PostgreSQL using app_runtime role.
Automatically skipped if DATABASE_URL is not configured or unreachable.
"""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest

from apps.api.config import settings

DATABASE_URL = settings.database_url.get_secret_value()
WORKER_DATABASE_URL = settings.worker_database_url.get_secret_value()


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
@pytest.mark.asyncio
async def test_live_app_runtime_connection_and_rls():
    """Verify live connection as app_runtime and validate transaction-scoped RLS settings."""
    conn = await asyncpg.connect(DATABASE_URL, ssl="require", statement_cache_size=0)
    try:
        # Verify authenticated role
        current_role = await conn.fetchval("SELECT current_user")
        assert current_role == "app_runtime"

        test_user = str(uuid4())
        test_org = str(uuid4())

        async with conn.transaction():
            # Set transaction-local RLS variables
            await conn.execute("SELECT set_config('app.current_user_id', $1, true)", test_user)
            await conn.execute("SELECT set_config('app.current_org_id', $1, true)", test_org)

            # Validate helper functions resolve them
            resolved_user = await conn.fetchval("SELECT public.current_app_user()")
            resolved_org = await conn.fetchval("SELECT public.current_app_org()")
            assert str(resolved_user) == test_user
            assert str(resolved_org) == test_org

            # Test get_user_memberships execution (should return 0 rows for non-existent user)
            memberships = await conn.fetch("SELECT * FROM public.get_user_memberships()")
            assert len(memberships) == 0

        # After transaction block exits, transaction-local settings MUST revert
        reverted_user = await conn.fetchval("SELECT public.current_app_user()")
        reverted_org = await conn.fetchval("SELECT public.current_app_org()")
        assert reverted_user is None
        assert reverted_org is None

    finally:
        await conn.close()


@pytest.mark.skipif(not WORKER_DATABASE_URL, reason="WORKER_DATABASE_URL is not configured")
@pytest.mark.asyncio
async def test_live_app_sync_connection_and_rls():
    """Verify live connection as app_sync, org-scoped session context, and permission boundaries."""
    conn = await asyncpg.connect(WORKER_DATABASE_URL, ssl="require", statement_cache_size=0)
    try:
        # Verify authenticated role
        current_role = await conn.fetchval("SELECT current_user")
        assert current_role == "app_sync"

        test_org = str(uuid4())

        async with conn.transaction():
            # Set worker org context
            await conn.execute("SELECT set_config('app.current_org_id', $1, true)", test_org)

            # Validate helper function resolves current_app_org
            resolved_org = await conn.fetchval("SELECT public.current_app_org()")
            assert str(resolved_org) == test_org

            # Verify RLS prevents seeing other tenants' sources
            sources = await conn.fetch("SELECT * FROM public.sources")
            assert len(sources) == 0

            # Verify app_sync is forbidden from writing to user-facing or sensitive tables
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute("INSERT INTO public.answers (question, answer_text, evidence_level, evidence_reason) VALUES ('q', 'a', 'documented', 'r')")

        # After transaction block exits, transaction-local settings revert
        reverted_org = await conn.fetchval("SELECT public.current_app_org()")
        assert reverted_org is None

    finally:
        await conn.close()

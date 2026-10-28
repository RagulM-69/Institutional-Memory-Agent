"""
PostgreSQL asynchronous connection pool layer for application runtime role.
Provides transaction-scoped execution and RLS context management.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

import asyncpg

from apps.api.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_worker_pool: asyncpg.Pool | None = None


async def init_pool(
    dsn: str | None = None,
    min_size: int = 1,
    max_size: int = 10,
    **kwargs,
) -> asyncpg.Pool:
    """Initialize the global asyncpg connection pool for app_runtime role."""
    global _pool
    if _pool is not None and not _pool.is_closing():
        return _pool

    target_dsn = dsn or settings.database_url.get_secret_value()
    if not target_dsn:
        raise RuntimeError("DATABASE_URL is not configured")

    # If connecting to a remote host without explicit ssl kwargs or dsn param, require SSL
    if "ssl" not in kwargs and ("localhost" not in target_dsn and "127.0.0.1" not in target_dsn):
        kwargs["ssl"] = "require"

    # Transaction poolers (Supavisor/PgBouncer port 6543) require statement_cache_size=0
    if "statement_cache_size" not in kwargs:
        kwargs["statement_cache_size"] = 0

    _pool = await asyncpg.create_pool(
        dsn=target_dsn,
        min_size=min_size,
        max_size=max_size,
        **kwargs,
    )
    return _pool


async def init_worker_pool(
    dsn: str | None = None,
    min_size: int = 1,
    max_size: int = 5,
    **kwargs,
) -> asyncpg.Pool:
    """Initialize the worker connection pool for app_sync role."""
    global _worker_pool
    if _worker_pool is not None and not _worker_pool.is_closing():
        return _worker_pool

    target_dsn = dsn or settings.worker_database_url.get_secret_value()
    if not target_dsn:
        raise RuntimeError("WORKER_DATABASE_URL is not configured")

    if "ssl" not in kwargs and ("localhost" not in target_dsn and "127.0.0.1" not in target_dsn):
        kwargs["ssl"] = "require"

    if "statement_cache_size" not in kwargs:
        kwargs["statement_cache_size"] = 0

    _worker_pool = await asyncpg.create_pool(
        dsn=target_dsn,
        min_size=min_size,
        max_size=max_size,
        **kwargs,
    )
    return _worker_pool


async def get_pool() -> asyncpg.Pool:
    """Get the active runtime connection pool, initializing it if necessary."""
    global _pool
    if _pool is None or _pool.is_closing():
        return await init_pool()
    return _pool


async def get_worker_pool() -> asyncpg.Pool:
    """Get the active worker connection pool, initializing it if necessary."""
    global _worker_pool
    if _worker_pool is None or _worker_pool.is_closing():
        return await init_worker_pool()
    return _worker_pool


async def close_pool() -> None:
    """Close all connection pools cleanly."""
    global _pool, _worker_pool
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _worker_pool is not None:
        await _worker_pool.close()
        _worker_pool = None


@asynccontextmanager
async def get_connection() -> AsyncIterator[asyncpg.Connection]:
    """Acquire a raw connection from the runtime pool and release it cleanly."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_worker_connection() -> AsyncIterator[asyncpg.Connection]:
    """Acquire a raw connection from the worker pool and release it cleanly."""
    pool = await get_worker_pool()
    async with pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def transaction_context(
    user_id: UUID | str | None = None,
    org_id: UUID | str | None = None,
    connection: asyncpg.Connection | None = None,
) -> AsyncIterator[asyncpg.Connection]:
    """
    Execute within an explicit transaction with transaction-local RLS session context.

    Uses `set_config(name, value, is_local=true)` so settings automatically revert
    upon COMMIT or ROLLBACK, completely preventing setting leakage across pooled
    connections or requests.
    """
    if connection is not None:
        async with connection.transaction():
            if user_id is not None:
                await connection.execute("SELECT set_config('app.current_user_id', $1, true)", str(user_id))
            if org_id is not None:
                await connection.execute("SELECT set_config('app.current_org_id', $1, true)", str(org_id))
            yield connection
    else:
        async with get_connection() as conn:
            async with conn.transaction():
                if user_id is not None:
                    await conn.execute("SELECT set_config('app.current_user_id', $1, true)", str(user_id))
                if org_id is not None:
                    await conn.execute("SELECT set_config('app.current_org_id', $1, true)", str(org_id))
                yield conn


@asynccontextmanager
async def worker_transaction_context(
    org_id: UUID | str,
    connection: asyncpg.Connection | None = None,
) -> AsyncIterator[asyncpg.Connection]:
    """
    Execute within an explicit transaction using the worker role (app_sync)
    with transaction-local organization RLS context (app.current_org_id).
    """
    if connection is not None:
        async with connection.transaction():
            await connection.execute("SELECT set_config('app.current_org_id', $1, true)", str(org_id))
            yield connection
    else:
        async with get_worker_connection() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.current_org_id', $1, true)", str(org_id))
                yield conn

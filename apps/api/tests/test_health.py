"""
Health endpoint test.

Uses httpx.AsyncClient with the ASGI transport so no running server is needed.
This test is not claimed to pass until it has been executed — see the
post-implementation summary for the actual run output.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.asyncio
async def test_health_returns_ok() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


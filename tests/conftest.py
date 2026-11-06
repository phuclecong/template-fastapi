"""Shared pytest fixtures.

The HTTP boundary is the single test seam: the ASGI app is driven through httpx's
``AsyncClient`` (not through internal functions).
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An AsyncClient bound to the app, exercising the real ASGI stack over HTTP."""
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client

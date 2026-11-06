"""Smoke tests: the app boots and serves over HTTP under /api/v1."""

from httpx import AsyncClient


async def test_health_check_served_under_api_v1(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_openapi_schema_is_served(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Template Dashboard API"
    assert "/api/v1/health" in schema["paths"]

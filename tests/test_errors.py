"""RFC 9457 error-envelope tests."""

from typing import Any

from httpx import AsyncClient


def _assert_problem_detail(body: dict[str, Any], status: int, code: str) -> None:
    assert set(body) == {"type", "title", "status", "detail", "code"}
    assert body["status"] == status
    assert body["code"] == code


async def test_unknown_route_returns_rfc9457_problem_detail(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    _assert_problem_detail(body, 404, "not_found")
    assert body["type"].endswith("/not_found")
    assert body["title"] == "Not found"
    assert body["detail"]


async def test_method_not_allowed_returns_rfc9457_problem_detail(
    client: AsyncClient,
) -> None:
    response = await client.post("/api/v1/health")

    assert response.status_code == 405
    _assert_problem_detail(response.json(), 405, "not_found")

"""RFC 9457 error-envelope tests."""

from typing import Any

from httpx import ASGITransport, AsyncClient

from app.core.errors import ErrorCode
from app.main import create_app

_EXPECTED_CODES = {
    "validation_error",
    "unauthorized",
    "forbidden",
    "not_found",
    "conflict",
    "too_many_requests",
    "internal_error",
}


def _assert_problem_detail(body: dict[str, Any], status: int, code: str) -> None:
    assert set(body) == {"type", "title", "status", "detail", "code", "message"}
    assert body["status"] == status
    assert body["code"] == code
    assert body["message"] == body["detail"]
    assert body["message"]


def test_error_code_set_is_fixed() -> None:
    assert {code.value for code in ErrorCode} == _EXPECTED_CODES


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


async def test_raised_problem_detail_error_carries_message(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")

    assert response.status_code == 401
    body = response.json()
    _assert_problem_detail(body, 401, "unauthorized")
    assert body["detail"] == "Invalid or expired access token."


async def test_validation_error_carries_message(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/login", json={})

    assert response.status_code == 422
    _assert_problem_detail(response.json(), 422, "validation_error")


async def test_unhandled_exception_handler_carries_message() -> None:
    # Drive a fresh app so the temporary route never leaks into the shared test app.
    test_app = create_app()

    @test_app.get("/_test/boom")
    async def _boom() -> None:
        raise RuntimeError("boom")

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        response = await test_client.get("/_test/boom")

    assert response.status_code == 500
    body = response.json()
    _assert_problem_detail(body, 500, "internal_error")
    assert body["detail"] == "An internal error occurred."

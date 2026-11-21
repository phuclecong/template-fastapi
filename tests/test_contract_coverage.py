"""Contract coverage: every operation declared in docs/openapi.yaml is implemented.

The contract is the single source of truth. It declares paths relative to the API
server (``/api/v1``), so each one is prefixed before matching. Framework-only routes
such as ``/health`` are absent from the contract and therefore out of scope.
"""

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from app.main import create_app

_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml"
_API_PREFIX = "/api/v1"
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head", "trace"})


def _contract_operations() -> list[tuple[str, str, str]]:
    """Return ``(path, method, operationId)`` for every contract operation."""
    contract: dict[str, Any] = yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))
    return [
        (path, method, operation["operationId"])
        for path, item in contract["paths"].items()
        for method, operation in item.items()
        if method in _HTTP_METHODS
    ]


def _generated_operations() -> set[tuple[str, str, str | None]]:
    """Return ``(path, method, operationId)`` for every route the app generates."""
    document = create_app().openapi()
    return {
        (path, method, operation.get("operationId"))
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in _HTTP_METHODS
    }


def test_every_contract_operation_is_implemented_with_its_operation_id() -> None:
    generated = _generated_operations()
    missing = [
        (f"{_API_PREFIX}{path}", method, operation_id)
        for path, method, operation_id in _contract_operations()
        if (f"{_API_PREFIX}{path}", method, operation_id) not in generated
    ]

    assert not missing, f"Contract operations missing from the app: {missing}"

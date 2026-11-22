"""Shared Pydantic validation helpers."""

from __future__ import annotations

from pydantic import BaseModel


def reject_null_for_non_nullable_fields(model: BaseModel, *field_names: str) -> None:
    """Raise ``ValueError`` if an explicitly supplied field is null.

    ``PATCH`` bodies distinguish omitted from explicit null via ``model_fields_set``;
    fields named here are not nullable per the contract, unlike clearable ones.
    """
    for name in field_names:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"{name} cannot be null")

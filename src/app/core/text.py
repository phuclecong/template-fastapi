"""Text-search helpers shared by the list endpoints."""

from __future__ import annotations


def escape_like(term: str) -> str:
    """Escape LIKE wildcards so the term matches a literal substring, not a pattern."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

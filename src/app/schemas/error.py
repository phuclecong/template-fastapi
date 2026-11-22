"""RFC 9457 problem-detail schema."""

from pydantic import BaseModel


class ProblemDetail(BaseModel):
    """An RFC 9457 problem detail plus a stable machine-readable ``code``."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    # Additive human-readable alias for ``detail`` used by the web client.
    message: str

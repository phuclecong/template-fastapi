"""ORM models.

Import every model module here so Alembic autogenerate can discover them.
"""

from app.models import role, session, task, user  # noqa: F401

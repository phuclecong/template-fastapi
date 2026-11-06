"""Environment-based application settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, populated from environment variables and a ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Template Dashboard API"
    app_version: str = "0.1.0"
    api_v1_str: str = "/api/v1"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    # database_url = 'postgresql://postgres:test123!@Localhost/...'
    problems_base_url: str = "https://api.example.com/problems"

    # Auth — access token is a JWT carrying the session id; refresh token is a
    # stateful server-side record (see docs/adr/0002-stateful-refresh-token-sessions.md).
    jwt_secret: str = "dev-only-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Rate limiting on the auth brute-force surface (login/register/refresh),
    # keyed by client IP per endpoint.
    auth_rate_limit_max_attempts: int = 5
    auth_rate_limit_window_seconds: int = 60

    # First-admin seed. Set ADMIN_EMAIL and ADMIN_PASSWORD together to create the
    # first admin at startup; registration always produces a `member`.
    admin_name: str = "Admin"
    admin_email: str | None = None
    admin_password: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()

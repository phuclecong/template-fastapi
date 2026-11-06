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
    problems_base_url: str = "https://api.example.com/problems"


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""
    return Settings()

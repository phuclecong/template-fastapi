"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.errors import register_exception_handlers

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup/shutdown tasks (e.g. dispose the DB engine on shutdown)."""
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    register_exception_handlers(application)
    application.include_router(api_router, prefix=settings.api_v1_str)
    return application


app = create_app()

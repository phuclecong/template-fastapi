"""Aggregate router for API v1."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, dashboard, events, health, password, roles, tasks, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(events.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(tasks.router)
api_router.include_router(dashboard.router)
api_router.include_router(password.router)

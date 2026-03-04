"""FastAPI application entry-point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.db.session import init_db
from app.schemas.api_models import HealthResponse
from app.utils.logging import setup_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    setup_logging()
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(router, prefix="/api/v1", tags=["validation-agent"])


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check() -> HealthResponse:
    return HealthResponse()

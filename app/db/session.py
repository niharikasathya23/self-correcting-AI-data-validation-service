"""Async SQLAlchemy engine and session factory.

Supports both SQLite (aiosqlite) for development and
PostgreSQL (asyncpg) for production via the DATABASE_URL env var.

Examples:
  SQLite:     DATABASE_URL=sqlite+aiosqlite:///./data_validation.db
  PostgreSQL: DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

# PostgreSQL benefits from connection pooling; SQLite doesn't.
_is_sqlite = settings.database_url.startswith("sqlite")
_pool_kwargs: dict = {"poolclass": NullPool} if _is_sqlite else {
    "pool_size": 20,
    "max_overflow": 10,
    "pool_pre_ping": True,
}

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    **_pool_kwargs,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that yields an async DB session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables (used at startup)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

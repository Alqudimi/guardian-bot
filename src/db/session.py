"""
Async SQLAlchemy session factory.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize schema in development or require an Alembic-managed schema."""
    settings = get_settings()
    engine = get_engine()

    if not settings.auto_create_tables:
        async with engine.connect() as conn:
            has_alembic_version = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).has_table("alembic_version")
            )
        if not has_alembic_version:
            raise RuntimeError(
                "Database schema is not migration-managed: run 'alembic upgrade head' first"
            )
        logger.info("database_migrations_expected")
        return

    import src.shop.models  # noqa: F401 — registers shop tables with metadata
    from src.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_initialized", auto_create_tables=True)


async def close_db() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("database_closed")

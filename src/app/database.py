"""
Database setup for SlackWoot.

Uses SQLAlchemy async with SQLite (dev) or PostgreSQL (production).
Connection URL is configured via DATABASE_URL in config.yaml or env var.

SQLite:   sqlite+aiosqlite:///./data/slackwoot.db
Postgres: postgresql+asyncpg://user:pass@host:5432/slackwoot
"""

import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# Engine is created once at module import — settings must be loaded first
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level.upper() == "DEBUG",  # Log SQL only in debug mode
    pool_pre_ping=True,                           # Detect stale connections
    # SQLite-specific: check_same_thread=False required for async
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a DB session and ensures cleanup."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create all tables if they don't exist. Called at app startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"Database initialized: {settings.database_url}")

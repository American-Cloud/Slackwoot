"""
Database setup for SlackWoot.

Uses SQLAlchemy async with SQLite (dev) or PostgreSQL (production).
Connection URL is read from the DATABASE_URL environment variable.

SQLite:   sqlite+aiosqlite:///./data/slackwoot.db  (default)
Postgres: postgresql+asyncpg://user:pass@host:5432/slackwoot
"""

import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import get_database_url

logger = logging.getLogger(__name__)

DATABASE_URL = get_database_url()


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True temporarily to debug SQL queries
    pool_pre_ping=True,  # Detect and recycle stale connections
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a DB session per request, commits on success."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """
    Create all tables if they don't exist. Called once at app startup.
    Safe to call repeatedly — existing tables are not modified.
    For schema changes after initial deployment, tables must be altered manually
    or the database recreated (acceptable for early-stage apps).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info(f"Database initialized: {DATABASE_URL}")

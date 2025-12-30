"""
Database session and engine configuration.

This file sets up the async database connection using SQLAlchemy + asyncpg.
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from app.core.config import settings


# Create the async database engine
# This is the connection to your PostgreSQL database
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # When DEBUG=True, prints SQL queries to console (helpful for learning)
    future=True,
)

# Create a session factory
# Sessions are used to interact with the database (read, write, update, delete)
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keeps data accessible after commit
)

# Alias for dependencies
AsyncSessionLocal = async_session_maker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Get a database session.
    
    This is used by FastAPI to provide a database connection to your API endpoints.
    The session is automatically closed when the request is done.
    
    Usage in a FastAPI endpoint:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            # use db to query the database
            pass
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_async_session_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager helper for async DB sessions (used in tests/scripts)."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

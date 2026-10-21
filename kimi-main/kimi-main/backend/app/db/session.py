"""Async database engine and session factory.

Usage
-----
FastAPI dependency injection::

    from app.db.session import get_session

    @router.get("/items")
    async def read_items(session: AsyncSession = Depends(get_session)):
        ...

Standalone async context (e.g. seeder, scripts)::

    async with get_session() as session:
        session.add(obj)
        await session.commit()
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from app.config import settings

# --------------------------------------------------------------------------- #
#  Engine                                                                      #
# --------------------------------------------------------------------------- #

engine = create_async_engine(
    settings.database_url,
    echo=False,            # must be False — echo sends to stdout which breaks MCP stdio JSON-RPC
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,         # discard stale connections silently
)

# --------------------------------------------------------------------------- #
#  Session factory                                                             #
# --------------------------------------------------------------------------- #

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,     # keep model attributes accessible after commit
    autoflush=False,
)

# --------------------------------------------------------------------------- #
#  Dependency / context manager                                                #
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional async session, rolling back automatically on error.

    Works both as a FastAPI dependency (via ``Depends``) and as a plain
    async context manager inside scripts or background tasks.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

# --------------------------------------------------------------------------- #
#  Table initialisation (called once at startup)                               #
# --------------------------------------------------------------------------- #

async def create_db_and_tables() -> None:
    """Create all SQLModel-registered tables that do not already exist.

    Called from the FastAPI lifespan handler on application startup.  Importing
    the models package here ensures every table class is registered with
    SQLAlchemy's metadata before ``create_all`` runs.
    """
    import app.db.models  # noqa: F401 — registers all table metadata

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

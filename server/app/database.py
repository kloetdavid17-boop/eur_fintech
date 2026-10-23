"""Database engine, session factory, and the get_session dependency.

For this MVP we keep schema management simple: ``init_db()`` creates any missing
tables from the SQLModel metadata on startup. A production version would swap
this for proper migrations (Alembic). Because there are no migrations, a schema
change to an existing dev DB needs a reset: ``docker compose down -v && up -d``.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    connect_args={"ssl": "require"} if settings.postgres_url else {},  # hosted Postgres needs TLS
    echo=False,
    pool_pre_ping=True,  # drop dead connections instead of erroring on first use
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create tables that don't exist yet. Imports models so they're registered."""
    from app import models  # noqa: F401  (ensures tables are attached to metadata)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, commit on success."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

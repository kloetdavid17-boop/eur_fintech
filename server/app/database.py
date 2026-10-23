"""Database engine, session factory, the get_session dependency, and ensure_schema().

Schema management is deliberately simple (no Alembic): ``ensure_schema()`` runs on startup
and is idempotent. It (1) creates any missing ``tt_*`` tables and (2) applies a small list of
additive ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` statements (Postgres only). It never
drops or modifies anything, and never touches the legacy ZZPay tables. See docs/database.md.
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.config import settings

logger = logging.getLogger("tradetrack.db")

engine = create_async_engine(
    settings.database_url,
    connect_args={"ssl": "require"} if settings.postgres_url else {},  # hosted Postgres needs TLS
    echo=False,
    pool_pre_ping=True,  # drop dead connections instead of erroring on first use
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Additive, idempotent column changes for tables that already exist in a live database.
# Append new entries here when a model gains a column (never edit or remove old entries).
# Each entry is plain SQL that is safe to run on every startup.
ADDITIVE_COLUMNS: list[str] = [
    # Example (already part of the first release, so it is a no-op today):
    # "ALTER TABLE tt_receipts ADD COLUMN IF NOT EXISTS processing_note VARCHAR",
]


async def ensure_schema(bind=None) -> None:
    """Create missing tt_* tables, then apply additive column changes (Postgres only)."""
    from app import models  # noqa: F401  (registers the tables on the metadata)

    target = bind or engine
    async with target.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        if conn.dialect.name == "postgresql":
            for statement in ADDITIVE_COLUMNS:
                await conn.execute(text(statement))
                logger.info("schema: %s", statement)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, commit on success."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

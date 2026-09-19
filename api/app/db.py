from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Serverless invocations are short-lived and a managed pooler is doing the
    # real pooling, so hold few connections and recycle them quickly rather
    # than sitting on handles a frozen function will never reuse.
    pool_size=settings.db_pool_size,
    max_overflow=0,
    pool_recycle=300,
    connect_args=settings.db_connect_args,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Roll back on any exception before the session is discarded.

    A failed write (an exclusion-constraint 409 is the common one) leaves the
    transaction in an aborted state. Without this, anything reusing the session
    -- a retry, or a shared session in tests -- fails with PendingRollbackError
    rather than the real error.
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

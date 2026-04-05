from importlib import import_module

from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


MODEL_MODULES = (
    "app.models.models",
    "app.models.scheduler_task",
    "app.models.workflow",
    "app.models.emby_sync_index",
    "app.models.archive",
)


def load_model_metadata() -> None:
    for module_name in MODEL_MODULES:
        import_module(module_name)


async def ensure_tables_exist(*table_names: str) -> bool:
    load_model_metadata()

    async with engine.begin() as conn:
        existing_tables = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        if table_names and all(
            table_name in existing_tables for table_name in table_names
        ):
            return False
        await conn.run_sync(Base.metadata.create_all)
        return True


def is_missing_table_error(exc: Exception, *table_names: str) -> bool:
    if not isinstance(exc, OperationalError):
        return False

    message = str(exc).lower()
    if "no such table" not in message:
        return False

    if not table_names:
        return True
    return any(table_name.lower() in message for table_name in table_names)


async def init_db():
    await ensure_tables_exist()


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

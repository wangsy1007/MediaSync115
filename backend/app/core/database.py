from importlib import import_module

from sqlalchemy import event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    connect_args={
        "timeout": 60,
    },
    poolclass=NullPool,
)


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
    "app.models.feiniu_sync_index",
    "app.models.archive",
    "app.models.watchlist",
    "app.models.person_follow",
)


DOWNLOAD_RECORD_COLUMN_SQL = {
    "offline_info_hash": "ALTER TABLE download_records ADD COLUMN offline_info_hash VARCHAR(100)",
    "offline_task_id": "ALTER TABLE download_records ADD COLUMN offline_task_id VARCHAR(100)",
    "offline_status": "ALTER TABLE download_records ADD COLUMN offline_status VARCHAR(50)",
    "offline_submitted_at": "ALTER TABLE download_records ADD COLUMN offline_submitted_at DATETIME",
    "offline_completed_at": "ALTER TABLE download_records ADD COLUMN offline_completed_at DATETIME",
}

SUBSCRIPTION_COLUMN_SQL = {
    "tv_scope": "ALTER TABLE subscriptions ADD COLUMN tv_scope VARCHAR(20) NOT NULL DEFAULT 'all'",
    "tv_season_number": "ALTER TABLE subscriptions ADD COLUMN tv_season_number INTEGER",
    "tv_episode_start": "ALTER TABLE subscriptions ADD COLUMN tv_episode_start INTEGER",
    "tv_episode_end": "ALTER TABLE subscriptions ADD COLUMN tv_episode_end INTEGER",
    "tv_follow_mode": "ALTER TABLE subscriptions ADD COLUMN tv_follow_mode VARCHAR(20) NOT NULL DEFAULT 'missing'",
    "tv_include_specials": "ALTER TABLE subscriptions ADD COLUMN tv_include_specials BOOLEAN DEFAULT 0",
    "preferred_resolutions": "ALTER TABLE subscriptions ADD COLUMN preferred_resolutions TEXT",
    "preferred_codecs": "ALTER TABLE subscriptions ADD COLUMN preferred_codecs TEXT",
    "preferred_hdr": "ALTER TABLE subscriptions ADD COLUMN preferred_hdr TEXT",
    "preferred_audio": "ALTER TABLE subscriptions ADD COLUMN preferred_audio TEXT",
    "preferred_subtitles": "ALTER TABLE subscriptions ADD COLUMN preferred_subtitles TEXT",
    "exclude_tags": "ALTER TABLE subscriptions ADD COLUMN exclude_tags TEXT",
    "min_size_gb": "ALTER TABLE subscriptions ADD COLUMN min_size_gb REAL",
    "max_size_gb": "ALTER TABLE subscriptions ADD COLUMN max_size_gb REAL",
}


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
        try:
            await conn.run_sync(Base.metadata.create_all)
        except OperationalError as exc:
            msg = str(exc or "").lower()
            if "already exists" in msg:
                pass
            else:
                raise
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


PERFORMANCE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_download_records_subscription_id "
    "ON download_records (subscription_id)",
    "CREATE INDEX IF NOT EXISTS ix_download_records_subscription_status "
    "ON download_records (subscription_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_subscriptions_active_created "
    "ON subscriptions (is_active, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_subscription_step_logs_created_at "
    "ON subscription_step_logs (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_watchlist_items_added_at "
    "ON watchlist_items (added_at)",
)


async def ensure_performance_indexes() -> None:
    async with engine.begin() as conn:
        for ddl in PERFORMANCE_INDEX_SQL:
            await conn.execute(text(ddl))


async def init_db():
    # 在最开始就用独立连接执行 PRAGMA，确保 WAL 和 busy_timeout 生效
    async with engine.connect() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=60000"))
        await conn.commit()
    await ensure_tables_exist()
    await ensure_subscription_columns()
    await ensure_download_record_columns()
    await ensure_performance_indexes()


async def ensure_subscription_columns() -> None:
    async with engine.begin() as conn:
        existing_tables = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        if "subscriptions" not in existing_tables:
            return
        existing_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"] for column in inspect(sync_conn).get_columns("subscriptions")
            }
        )
        for column_name, ddl in SUBSCRIPTION_COLUMN_SQL.items():
            if column_name not in existing_columns:
                await conn.execute(text(ddl))


async def ensure_download_record_columns() -> None:
    async with engine.begin() as conn:
        existing_tables = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        if "download_records" not in existing_tables:
            return
        existing_columns = await conn.run_sync(
            lambda sync_conn: {
                column["name"]
                for column in inspect(sync_conn).get_columns("download_records")
            }
        )
        for column_name, ddl in DOWNLOAD_RECORD_COLUMN_SQL.items():
            if column_name not in existing_columns:
                await conn.execute(text(ddl))
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_download_records_offline_info_hash "
                "ON download_records (offline_info_hash)"
            )
        )


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

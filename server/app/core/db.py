import json
import os
import uuid

import asyncpg

from .config import DATABASE_URL, DB_NAME, DEFAULT_USER_ID
from .logger import logger

_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "../../migrations")

_pool: asyncpg.Pool | None = None


def _db_connection_string():
    return DATABASE_URL if DB_NAME in DATABASE_URL else (
        f"postgres://postgres:postgres@127.0.0.1:54329/{DB_NAME}?sslmode=disable"
    )


async def _ensure_database_exists():
    admin_conn = await asyncpg.connect(dsn=DATABASE_URL)
    try:
        exists = await admin_conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", DB_NAME)
        if not exists:
            logger.info(f'Database "{DB_NAME}" does not exist. Creating it...')
            await admin_conn.execute(f'CREATE DATABASE "{DB_NAME}"')
        else:
            logger.info(f'Database "{DB_NAME}" already exists.')
    finally:
        await admin_conn.close()


async def _init_connection(conn: asyncpg.Connection):
    # Mirrors the JS `pg` driver's defaults: uuid columns come back as plain
    # strings and jsonb columns come back already-parsed, so route code that
    # was ported 1:1 from JS doesn't need extra (de)serialization glue.
    await conn.set_type_codec(
        "uuid", schema="pg_catalog", encoder=str, decoder=str, format="text"
    )
    # Call sites (ported 1:1 from JS, which always passed JSON.stringify(x))
    # already hand jsonb params as pre-serialized strings — only auto-encode
    # here if a caller passes a raw dict/list, to avoid double-encoding the
    # common case into a quoted string-within-a-string.
    await conn.set_type_codec(
        "jsonb",
        schema="pg_catalog",
        encoder=lambda v: v if isinstance(v, str) else json.dumps(v),
        decoder=json.loads,
        format="text",
    )


async def init_db():
    global _pool
    await _ensure_database_exists()

    _pool = await asyncpg.create_pool(dsn=_db_connection_string(), init=_init_connection)

    async with _pool.acquire() as conn:
        async with conn.transaction():
            table_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                  SELECT FROM information_schema.tables
                  WHERE table_schema = 'public' AND table_name = 'users'
                );
                """
            )
            if not table_exists:
                logger.info("Running initial database migrations...")
                with open(os.path.join(_MIGRATIONS_DIR, "001_initial_schema.sql")) as f:
                    await conn.execute(f.read())
                logger.info("Database migrations completed successfully.")
            else:
                logger.info("Tables already exist. Skipping migrations.")

            for filename in [
                "002_knowledge_metadata.sql",
                "003_user_memory.sql",
                "004_conversation_summary.sql",
                "005_message_document.sql",
                "006_file_hash_dedup.sql",
                "007_interview_coach.sql",
            ]:
                path = os.path.join(_MIGRATIONS_DIR, filename)
                if os.path.exists(path):
                    with open(path) as f:
                        await conn.execute(f.read())

            await conn.execute(
                """
                INSERT INTO users (id, email, password_hash)
                VALUES ($1, $2, $3)
                ON CONFLICT (id) DO NOTHING;
                """,
                DEFAULT_USER_ID,
                "dr.john.doe@nova.ai",
                "hashedpassword",
            )


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized — call init_db() first")
    return _pool


async def query(text: str, params: list | None = None) -> dict:
    """Mirrors the shape of the JS `pg` driver's query result: {rows, rowCount}."""
    params = params or []
    pool = get_pool()
    async with pool.acquire() as conn:
        lowered = text.strip().lower()
        if "returning" in lowered or lowered.startswith("select"):
            rows = await conn.fetch(text, *params)
            return {"rows": [dict(r) for r in rows], "rowCount": len(rows)}
        tag = await conn.execute(text, *params)
        count_str = tag.split()[-1]
        count = int(count_str) if count_str.isdigit() else 0
        return {"rows": [], "rowCount": count}


async def close_db():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None

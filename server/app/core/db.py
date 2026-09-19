import json
import os
import re
import sqlite3
import uuid

import asyncpg

from .config import DATABASE_URL, DB_NAME, DEFAULT_USER_ID
from .logger import logger

_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "../../migrations")
_SQLITE_PATH = os.path.join(os.path.dirname(__file__), "../../nova_ai.db")

_pool: asyncpg.Pool | None = None
_use_sqlite = False
_sqlite_conn: sqlite3.Connection | None = None


def _db_connection_string():
    return DATABASE_URL if DB_NAME in DATABASE_URL else (
        f"postgres://postgres:postgres@127.0.0.1:54329/{DB_NAME}?sslmode=disable"
    )


async def _ensure_database_exists():
    admin_conn = await asyncpg.connect(dsn=DATABASE_URL, timeout=3)
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
    await conn.set_type_codec(
        "uuid", schema="pg_catalog", encoder=str, decoder=str, format="text"
    )
    await conn.set_type_codec(
        "jsonb",
        schema="pg_catalog",
        encoder=lambda v: v if isinstance(v, str) else json.dumps(v),
        decoder=json.loads,
        format="text",
    )


def _get_sqlite_conn():
    conn = sqlite3.connect(_SQLITE_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def _init_sqlite():
    with _get_sqlite_conn() as conn:
        cursor = conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                summary_updated_at TEXT,
                summary_message_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                document TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS uploaded_files (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                message_id TEXT,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                hash TEXT,
                source_type TEXT DEFAULT 'document',
                ingest_status TEXT DEFAULT 'pending',
                qdrant_collection TEXT,
                source_url TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS document_chunks (
                id TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL,
                page_number INTEGER,
                line_start INTEGER,
                line_end INTEGER,
                qdrant_point_id TEXT
            );

            CREATE TABLE IF NOT EXISTS indexing_jobs (
                id TEXT PRIMARY KEY,
                file_id TEXT,
                status TEXT DEFAULT 'queued',
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_memories (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message_id TEXT,
                fact TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS conversation_summaries (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                last_message_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS interview_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS interview_problems (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                problem_index INTEGER NOT NULL,
                category TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                starter_code TEXT,
                constraints TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS interview_submissions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                problem_id TEXT NOT NULL,
                code TEXT NOT NULL,
                result TEXT NOT NULL,
                feedback TEXT,
                score INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS practice_problems (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                problem_index INTEGER NOT NULL,
                category TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                starter_code TEXT,
                constraints TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cursor.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash) VALUES (?, ?, ?)",
            (DEFAULT_USER_ID, "dr.john.doe@nova.ai", "hashedpassword")
        )
        conn.commit()
        logger.info("Initialized local SQLite database (nova_ai.db) fallback.")


async def init_db():
    global _pool, _use_sqlite
    try:
        await _ensure_database_exists()
        _pool = await asyncpg.create_pool(dsn=_db_connection_string(), init=_init_connection, timeout=1)
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

                for filename in [
                    "002_user_memories.sql",
                    "003_conversation_summaries.sql",
                    "004_document_analysis_retrieval.sql",
                    "005_interview_coach_tables.sql",
                ]:
                    filepath = os.path.join(_MIGRATIONS_DIR, filename)
                    if os.path.exists(filepath):
                        with open(filepath) as f:
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
        _use_sqlite = False
        logger.info("PostgreSQL database initialized and connected.")
    except Exception as err:
        logger.warn(f"PostgreSQL connection failed ({err}). Using SQLite fallback.")
        _use_sqlite = True
        _init_sqlite()


def get_pool() -> asyncpg.Pool:
    if _pool is None and not _use_sqlite:
        raise RuntimeError("Database pool not initialized — call init_db() first")
    return _pool


def _execute_sqlite_query(text: str, params: list) -> dict:
    sql = text
    # Handle ANY array query syntax e.g. message_id = ANY($1::uuid[])
    any_match = re.search(r"=\s*ANY\(\$(\d+)(?:::\w+\[\])?\)", sql, re.I)
    if any_match:
        param_idx = int(any_match.group(1)) - 1
        arr_val = params[param_idx] if param_idx < len(params) else []
        if isinstance(arr_val, (list, tuple)) and len(arr_val) > 0:
            placeholders = ", ".join(["?"] * len(arr_val))
            sql = re.sub(r"=\s*ANY\(\$\d+(?:::\w+\[\])?\)", f"IN ({placeholders})", sql, flags=re.I)
            new_params = []
            for i, p in enumerate(params):
                if i == param_idx:
                    new_params.extend(arr_val)
                else:
                    new_params.append(p)
            params = new_params
        else:
            sql = re.sub(r"=\s*ANY\(\$\d+(?:::\w+\[\])?\)", "IN (NULL)", sql, flags=re.I)
            params = [p for i, p in enumerate(params) if i != param_idx]

    # Convert $1, $2, $3 to ?
    sql = re.sub(r"\$\d+", "?", sql)

    # Convert PostgreSQL functions / syntax to SQLite equivalents
    sql = re.sub(r"\bgen_random_uuid\(\)", "?", sql, flags=re.I)
    sql = re.sub(r"\buuid_generate_v4\(\)", "?", sql, flags=re.I)

    # Strip RETURNING clause for SQLite execution
    returning_match = re.search(r"\s+RETURNING\s+.*$", sql, re.I)
    has_returning = bool(returning_match)
    if has_returning:
        sql = sql[:returning_match.start()]

    # Format JSON parameters
    clean_params = []
    for p in params:
        if isinstance(p, (dict, list)):
            clean_params.append(json.dumps(p))
        else:
            clean_params.append(p)

    lowered = text.strip().lower()

    with _get_sqlite_conn() as conn:
        cursor = conn.cursor()
        if lowered.startswith("select") or "returning" in lowered and not lowered.startswith("insert") and not lowered.startswith("update") and not lowered.startswith("delete"):
            cursor.execute(sql, clean_params)
            rows = [dict(r) for r in cursor.fetchall()]
            for r in rows:
                for k, v in r.items():
                    if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                        try:
                            r[k] = json.loads(v)
                        except Exception:
                            pass
            return {"rows": rows, "rowCount": len(rows)}
        elif lowered.startswith("insert"):
            table_match = re.search(r"INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)", sql, re.I)
            table_name = table_match.group(1) if table_match else None
            cols = [c.strip().lower() for c in table_match.group(2).split(",")] if table_match else []

            inserted_id = None
            if cols and "id" not in cols:
                inserted_id = str(uuid.uuid4())
                cols_str = ", ".join(["id", *cols])
                placeholders = ", ".join(["?", *["?"] * len(clean_params)])
                sql = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})"
                clean_params = [inserted_id, *clean_params]
            elif clean_params and isinstance(clean_params[0], str) and len(clean_params[0]) > 10:
                inserted_id = clean_params[0]

            cursor.execute(sql, clean_params)
            conn.commit()
            row_count = cursor.rowcount

            inserted_rows = []
            if has_returning and table_name:
                if inserted_id:
                    cursor.execute(f"SELECT * FROM {table_name} WHERE id = ?", (inserted_id,))
                else:
                    cursor.execute(f"SELECT * FROM {table_name} WHERE rowid = ?", (cursor.lastrowid,))
                inserted_rows = [dict(r) for r in cursor.fetchall()]
                for r in inserted_rows:
                    for k, v in r.items():
                        if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                            try:
                                r[k] = json.loads(v)
                            except Exception:
                                pass
            return {"rows": inserted_rows, "rowCount": row_count}
        else:
            cursor.execute(sql, clean_params)
            conn.commit()
            return {"rows": [], "rowCount": cursor.rowcount}


async def query(text: str, params: list | None = None) -> dict:
    params = params or []
    if _use_sqlite:
        import asyncio
        return await asyncio.to_thread(_execute_sqlite_query, text, params)

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
    global _pool, _sqlite_conn
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _sqlite_conn is not None:
        _sqlite_conn.close()
        _sqlite_conn = None


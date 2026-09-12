import asyncio
import json
import os
import re
import time
import uuid

import asyncpg

from .config import DATABASE_URL, DB_NAME, DEFAULT_USER_ID
from .logger import logger

_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "../../migrations")

_pool: asyncpg.Pool | None = None
_is_fallback: bool = False
_JSON_DB_PATH = os.path.join(os.path.dirname(__file__), "../../nova_ai_db.json")
_db_lock = asyncio.Lock()


def _read_json_db() -> dict:
    if not os.path.exists(_JSON_DB_PATH):
        initial = {
            "users": [
                {
                    "id": DEFAULT_USER_ID,
                    "email": "dr.john.doe@nova.ai",
                    "password_hash": "hashedpassword",
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            ],
            "chats": [],
            "messages": [],
            "uploaded_files": [],
            "document_chunks": [],
            "user_memory": [],
            "indexing_jobs": [],
            "practice_problems": [],
            "interview_sessions": [],
            "session_submissions": [],
        }
        with open(_JSON_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(initial, f, indent=2)
        return initial
    try:
        with open(_JSON_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read JSON DB: {e}")
        return {
            "users": [],
            "chats": [],
            "messages": [],
            "uploaded_files": [],
            "document_chunks": [],
            "user_memory": [],
            "indexing_jobs": [],
            "practice_problems": [],
            "interview_sessions": [],
            "session_submissions": [],
        }


def _write_json_db(data: dict) -> None:
    temp_path = f"{_JSON_DB_PATH}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, _JSON_DB_PATH)


def _query_json_db(text: str, params: list | None = None) -> dict:
    params = params or []
    sql = " ".join(text.lower().split()).strip()
    data = _read_json_db()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # 1. SELECT 1 / health check
    if sql == "select 1":
        return {"rows": [{"?column?": 1}], "rowCount": 1}

    # 2. SELECT * FROM chats WHERE user_id = $1 ORDER BY updated_at DESC
    if "from chats" in sql and "order by updated_at desc" in sql:
        user_id = params[0] if params else DEFAULT_USER_ID
        chats = [c for c in data.get("chats", []) if c.get("user_id") == user_id]
        chats.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return {"rows": chats, "rowCount": len(chats)}

    # 3. INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *
    if "insert into chats" in sql and "returning" in sql:
        user_id = params[0] if len(params) > 0 else DEFAULT_USER_ID
        title = params[1] if len(params) > 1 else "New Chat"
        new_chat = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "title": title,
            "summary": None,
            "summary_updated_at": None,
            "summary_message_count": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        data.setdefault("chats", []).append(new_chat)
        _write_json_db(data)
        return {"rows": [new_chat], "rowCount": 1}

    # 4. UPDATE chats SET title = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2 AND user_id = $3 RETURNING *
    if "update chats set title" in sql and "returning" in sql:
        title = params[0]
        chat_id = params[1]
        user_id = params[2] if len(params) > 2 else DEFAULT_USER_ID
        for chat in data.get("chats", []):
            if chat.get("id") == chat_id and chat.get("user_id") == user_id:
                chat["title"] = title
                chat["updated_at"] = now_iso
                _write_json_db(data)
                return {"rows": [chat], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

    # 5. DELETE FROM chats WHERE id = $1 AND user_id = $2
    if "delete from chats" in sql:
        chat_id = params[0]
        user_id = params[1] if len(params) > 1 else DEFAULT_USER_ID
        orig_len = len(data.get("chats", []))
        data["chats"] = [c for c in data.get("chats", []) if not (c.get("id") == chat_id and c.get("user_id") == user_id)]
        if len(data["chats"]) < orig_len:
            data["messages"] = [m for m in data.get("messages", []) if m.get("chat_id") != chat_id]
            _write_json_db(data)
            return {"rows": [{"id": chat_id}], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

    # 6. SELECT id FROM chats WHERE id = $1 AND user_id = $2
    if "select id from chats" in sql and "where id = $1" in sql:
        chat_id = params[0]
        user_id = params[1] if len(params) > 1 else DEFAULT_USER_ID
        match = [c for c in data.get("chats", []) if c.get("id") == chat_id and c.get("user_id") == user_id]
        return {"rows": [{"id": match[0]["id"]}] if match else [], "rowCount": len(match)}

    # 7. SELECT summary, summary_message_count FROM chats WHERE id = $1
    if "from chats" in sql and "summary" in sql and sql.startswith("select"):
        chat_id = params[0]
        match = [c for c in data.get("chats", []) if c.get("id") == chat_id]
        if match:
            return {"rows": [{"summary": match[0].get("summary"), "summary_message_count": match[0].get("summary_message_count", 0)}], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

    # 8. UPDATE chats SET summary = $1...
    if "update chats set summary" in sql:
        summary, count, chat_id = params[0], params[1], params[2]
        for chat in data.get("chats", []):
            if chat.get("id") == chat_id:
                chat["summary"] = summary
                chat["summary_updated_at"] = now_iso
                chat["summary_message_count"] = count
                _write_json_db(data)
                return {"rows": [], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

    # 9. UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1
    if "update chats set updated_at" in sql:
        chat_id = params[0]
        for chat in data.get("chats", []):
            if chat.get("id") == chat_id:
                chat["updated_at"] = now_iso
                _write_json_db(data)
                return {"rows": [], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

    # 10. SELECT * FROM messages WHERE chat_id = $1 ORDER BY created_at ASC
    # or SELECT id FROM messages WHERE chat_id = $1
    if "from messages" in sql and "where chat_id = $1" in sql:
        chat_id = params[0]
        messages = [m for m in data.get("messages", []) if m.get("chat_id") == chat_id]
        messages.sort(key=lambda x: x.get("created_at", ""))
        if sql.startswith("select id from messages"):
            return {"rows": [{"id": m["id"]} for m in messages], "rowCount": len(messages)}
        return {"rows": messages, "rowCount": len(messages)}

    # 11. INSERT INTO messages (chat_id, role, content[, document]) VALUES (...) RETURNING *
    if "insert into messages" in sql:
        chat_id = params[0]
        role = params[1]
        content = params[2]
        doc = params[3] if len(params) > 3 else None
        if isinstance(doc, str):
            try:
                doc = json.loads(doc)
            except Exception:
                pass
        new_msg = {
            "id": str(uuid.uuid4()),
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "document": doc,
            "created_at": now_iso,
        }
        data.setdefault("messages", []).append(new_msg)
        _write_json_db(data)
        return {"rows": [new_msg], "rowCount": 1}

    # 12. SELECT ... FROM uploaded_files WHERE message_id = ANY(...)
    if "from uploaded_files" in sql and "message_id" in sql:
        msg_ids = params[0] if params else []
        if isinstance(msg_ids, str):
            msg_ids = [msg_ids]
        matched = [f for f in data.get("uploaded_files", []) if f.get("message_id") in msg_ids]
        return {"rows": matched, "rowCount": len(matched)}

    # 13. SELECT ... FROM uploaded_files WHERE user_id = $1 AND file_hash = $2
    if "from uploaded_files" in sql and "file_hash" in sql:
        user_id = params[0]
        file_hash = params[1]
        matched = [f for f in data.get("uploaded_files", []) if f.get("user_id") == user_id and f.get("file_hash") == file_hash and f.get("ingest_status") == "indexed"]
        return {"rows": matched, "rowCount": len(matched)}

    # 14. SELECT * FROM uploaded_files WHERE user_id = $1
    if "from uploaded_files" in sql and "where user_id = $1" in sql:
        user_id = params[0] if params else DEFAULT_USER_ID
        matched = [f for f in data.get("uploaded_files", []) if f.get("user_id") == user_id]
        matched.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return {"rows": matched, "rowCount": len(matched)}

    # 15. INSERT INTO uploaded_files ... RETURNING *
    if "insert into uploaded_files" in sql:
        msg_id, user_id, filename, orig_name, mime, size, path = params[0], params[1], params[2], params[3], params[4], params[5], params[6]
        file_hash = params[7] if len(params) > 7 else None
        status = params[8] if len(params) > 8 else "processing"
        new_file = {
            "id": str(uuid.uuid4()),
            "message_id": msg_id,
            "user_id": user_id or DEFAULT_USER_ID,
            "filename": filename,
            "original_filename": orig_name,
            "mime_type": mime,
            "size_bytes": size,
            "file_path": path,
            "file_hash": file_hash,
            "ingest_status": status,
            "created_at": now_iso,
        }
        data.setdefault("uploaded_files", []).append(new_file)
        _write_json_db(data)
        return {"rows": [new_file], "rowCount": 1}

    # 16. UPDATE uploaded_files SET message_id = $1 WHERE id = $2
    if "update uploaded_files set message_id" in sql:
        msg_id, file_id = params[0], params[1]
        for f in data.get("uploaded_files", []):
            if f.get("id") == file_id:
                f["message_id"] = msg_id
                _write_json_db(data)
                return {"rows": [], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

    # 17. UPDATE uploaded_files SET ingest_status = $1 WHERE id = $2
    if "update uploaded_files set ingest_status" in sql:
        status_val = "indexed" if "indexed" in sql else "failed"
        file_id = params[0]
        for f in data.get("uploaded_files", []):
            if f.get("id") == file_id or f.get("file_hash") == file_id:
                f["ingest_status"] = status_val
                _write_json_db(data)
                return {"rows": [], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

    # 18. INSERT INTO indexing_jobs ... RETURNING id
    if "insert into indexing_jobs" in sql:
        job_id = str(uuid.uuid4())
        new_job = {"id": job_id, "file_id": params[0], "status": params[1] if len(params) > 1 else "running", "created_at": now_iso}
        data.setdefault("indexing_jobs", []).append(new_job)
        _write_json_db(data)
        return {"rows": [{"id": job_id}], "rowCount": 1}

    # 19. UPDATE indexing_jobs SET status = ...
    if "update indexing_jobs set status" in sql:
        return {"rows": [], "rowCount": 1}

    # 20. INSERT INTO document_chunks ... RETURNING id
    if "insert into document_chunks" in sql:
        file_id, content, embedding = params[0], params[1], params[2]
        page_no = params[3] if len(params) > 3 else None
        if isinstance(embedding, str):
            try:
                embedding = json.loads(embedding)
            except Exception:
                pass
        new_chunk = {
            "id": str(uuid.uuid4()),
            "file_id": file_id,
            "content": content,
            "embedding": embedding,
            "page_number": page_no,
            "created_at": now_iso,
        }
        data.setdefault("document_chunks", []).append(new_chunk)
        _write_json_db(data)
        return {"rows": [{"id": new_chunk["id"]}], "rowCount": 1}

    # 21. SELECT * FROM document_chunks WHERE file_id = ANY(...)
    if "from document_chunks" in sql and "file_id" in sql:
        f_ids = params[0] if params else []
        if isinstance(f_ids, str):
            f_ids = [f_ids]
        chunks = [c for c in data.get("document_chunks", []) if c.get("file_id") in f_ids]
        return {"rows": chunks, "rowCount": len(chunks)}

    # 22. INSERT INTO user_memory
    if "insert into user_memory" in sql:
        user_id, chat_id, m_type, content, embedding = params[0], params[1], params[2], params[3], params[4]
        if isinstance(embedding, str):
            try:
                embedding = json.loads(embedding)
            except Exception:
                pass
        new_mem = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "chat_id": chat_id,
            "type": m_type,
            "content": content,
            "embedding": embedding,
            "created_at": now_iso,
        }
        data.setdefault("user_memory", []).append(new_mem)
        _write_json_db(data)
        return {"rows": [new_mem], "rowCount": 1}

    # 23. SELECT * FROM user_memory
    if "from user_memory" in sql:
        user_id = params[0] if params else DEFAULT_USER_ID
        mems = [m for m in data.get("user_memory", []) if m.get("user_id") == user_id]
        if "and chat_id = $2" in sql and len(params) > 1:
            chat_id = params[1]
            mems = [m for m in mems if m.get("chat_id") == chat_id]
        return {"rows": mems, "rowCount": len(mems)}

    logger.warn(f"Unhandled query in JSON DB fallback: {sql}")
    return {"rows": [], "rowCount": 0}


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


async def init_db():
    global _pool, _is_fallback
    try:
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
        _is_fallback = False
        logger.info("Postgres connected successfully.")
    except Exception as err:
        logger.warn(f"Postgres unreachable ({err}). Using built-in JSON database fallback.")
        _is_fallback = True
        _read_json_db()


def get_pool() -> asyncpg.Pool:
    if _pool is None and not _is_fallback:
        raise RuntimeError("Database pool not initialized — call init_db() first")
    return _pool


async def query(text: str, params: list | None = None) -> dict:
    params = params or []
    if _is_fallback or _pool is None:
        async with _db_lock:
            return _query_json_db(text, params)

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

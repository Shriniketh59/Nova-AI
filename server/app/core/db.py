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
                    "name": "Dr. John Doe",
                    "password_hash": "scrypt:16384:8:1$X//NOsyAubmKAEo4fv6EBg==$MOl4hFjHbGOSDyc3lb+OtLIjmi1qiDrfnIHECNGr4q0=",
                    "profile_image": None,
                    "auth_provider": "local",
                    "provider_user_id": None,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "last_login": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "reset_token": None,
                    "reset_token_expires_at": None,
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
            "user_daily_token_usage": [],
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
            "user_daily_token_usage": [],
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

    # User query 1: SELECT ... FROM users WHERE email = $1
    if "from users" in sql and "where email = $1" in sql:
        email = str(params[0]).strip().lower() if params else ""
        users = [u for u in data.get("users", []) if str(u.get("email", "")).strip().lower() == email]
        return {"rows": users, "rowCount": len(users)}

    # User query 2: SELECT ... FROM users WHERE auth_provider = $1 AND provider_user_id = $2
    if "from users" in sql and "auth_provider = $1" in sql and "provider_user_id = $2" in sql:
        provider = str(params[0]) if params else ""
        p_uid = str(params[1]) if len(params) > 1 else ""
        users = [u for u in data.get("users", []) if u.get("auth_provider") == provider and str(u.get("provider_user_id")) == p_uid]
        return {"rows": users, "rowCount": len(users)}

    # User query 3: SELECT ... FROM users WHERE id = $1
    if "from users" in sql and "where id = $1" in sql:
        user_id = str(params[0]) if params else ""
        users = [u for u in data.get("users", []) if str(u.get("id")) == user_id]
        return {"rows": users, "rowCount": len(users)}

    # User query 4: SELECT ... FROM users WHERE reset_token = $1
    if "from users" in sql and "reset_token = $1" in sql:
        token = str(params[0]) if params else ""
        users = [u for u in data.get("users", []) if u.get("reset_token") == token]
        return {"rows": users, "rowCount": len(users)}

    # User query 5: INSERT INTO users ... RETURNING *
    if "insert into users" in sql:
        user_id = str(params[0]) if len(params) > 0 and params[0] else str(uuid.uuid4())
        email = str(params[1]) if len(params) > 1 else ""
        password_hash = str(params[2]) if len(params) > 2 else ""
        name = str(params[3]) if len(params) > 3 and params[3] is not None else email.split("@")[0].capitalize()
        profile_image = str(params[4]) if len(params) > 4 and params[4] is not None else None
        auth_provider = str(params[5]) if len(params) > 5 and params[5] is not None else "local"
        provider_user_id = str(params[6]) if len(params) > 6 and params[6] is not None else None
        new_user = {
            "id": user_id,
            "email": email,
            "password_hash": password_hash,
            "name": name,
            "profile_image": profile_image,
            "auth_provider": auth_provider,
            "provider_user_id": provider_user_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "last_login": now_iso,
            "reset_token": None,
            "reset_token_expires_at": None,
        }
        data.setdefault("users", []).append(new_user)
        _write_json_db(data)
        return {"rows": [new_user], "rowCount": 1}

    # User query 6: UPDATE users SET last_login = ... WHERE id = $1
    if "update users" in sql and "last_login" in sql:
        user_id = str(params[0]) if params else ""
        for u in data.get("users", []):
            if str(u.get("id")) == user_id:
                u["last_login"] = now_iso
                _write_json_db(data)
                return {"rows": [u], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

    # User query 7: UPDATE users SET reset_token = $1, reset_token_expires_at = $2, updated_at = ... WHERE id = $3
    if "update users" in sql and "reset_token =" in sql and "where id =" in sql and "password_hash" not in sql:
        reset_token = params[0]
        expires_at = params[1]
        user_id = str(params[2])
        for u in data.get("users", []):
            if str(u.get("id")) == user_id:
                u["reset_token"] = reset_token
                u["reset_token_expires_at"] = expires_at
                u["updated_at"] = now_iso
                _write_json_db(data)
                return {"rows": [u], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

    # User query 8: UPDATE users SET password_hash = $1... WHERE id = $2
    if "update users" in sql and "password_hash" in sql:
        new_hash = params[0]
        user_id = str(params[1])
        for u in data.get("users", []):
            if str(u.get("id")) == user_id:
                u["password_hash"] = new_hash
                u["reset_token"] = None
                u["reset_token_expires_at"] = None
                u["updated_at"] = now_iso
                _write_json_db(data)
                return {"rows": [u], "rowCount": 1}
        return {"rows": [], "rowCount": 0}

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
        user_id = params[0] if len(params) > 0 else DEFAULT_USER_ID
        chat_id = params[1] if len(params) > 1 else None
        m_type = params[2] if len(params) > 2 else "fact"
        content = params[3] if len(params) > 3 else ""
        embedding = params[4] if len(params) > 4 else []
        topic = params[5] if len(params) > 5 else None
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
            "topic": topic,
            "is_active": True,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        data.setdefault("user_memory", []).append(new_mem)
        _write_json_db(data)
        return {"rows": [new_mem], "rowCount": 1}

    # 22b. UPDATE user_memory (supersede / deactivate stale memory)
    if "update user_memory" in sql:
        if "is_active = false" in sql or "is_active = $1" in sql:
            target_ids = []
            if "where id = $" in sql and params:
                target_ids = [params[-1]]
            elif "where id = any" in sql and params:
                param_val = params[0]
                target_ids = param_val if isinstance(param_val, list) else [param_val]
            elif "where user_id = $1 and topic = $2" in sql and len(params) >= 2:
                u_id, t_topic = params[0], params[1]
                for m in data.get("user_memory", []):
                    if m.get("user_id") == u_id and m.get("topic") == t_topic:
                        m["is_active"] = False
                        m["updated_at"] = now_iso
                _write_json_db(data)
                return {"rows": [], "rowCount": 1}

            for m in data.get("user_memory", []):
                if m.get("id") in target_ids:
                    m["is_active"] = False
                    m["updated_at"] = now_iso
            _write_json_db(data)
            return {"rows": [], "rowCount": len(target_ids)}

        if "content = $1" in sql and "where id =" in sql:
            new_content = params[0]
            new_emb = params[1] if len(params) > 1 else None
            mem_id = params[2] if len(params) > 2 else None
            if isinstance(new_emb, str):
                try:
                    new_emb = json.loads(new_emb)
                except Exception:
                    pass
            for m in data.get("user_memory", []):
                if m.get("id") == mem_id:
                    m["content"] = new_content
                    if new_emb is not None:
                        m["embedding"] = new_emb
                    m["updated_at"] = now_iso
                    m["is_active"] = True
                    _write_json_db(data)
                    return {"rows": [m], "rowCount": 1}
            return {"rows": [], "rowCount": 0}

    # 23. SELECT * FROM user_memory
    if "from user_memory" in sql:
        user_id = params[0] if params else DEFAULT_USER_ID
        mems = [m for m in data.get("user_memory", []) if m.get("user_id") == user_id]
        if "is_active = true" in sql or "is_active" not in sql:
            mems = [m for m in mems if m.get("is_active", True) is not False]
        if "and chat_id = $2" in sql and len(params) > 1:
            chat_id = params[1]
            mems = [m for m in mems if m.get("chat_id") == chat_id]
        if "type in ('fact', 'preference')" in sql or "type in ('fact','preference')" in sql:
            mems = [m for m in mems if m.get("type") in ("fact", "preference")]
        elif "type = 'project'" in sql:
            mems = [m for m in mems if m.get("type") == "project"]
        return {"rows": mems, "rowCount": len(mems)}

    # 24. SELECT / INSERT / UPDATE user_daily_token_usage
    if "from user_daily_token_usage" in sql:
        user_id = params[0] if len(params) > 0 else DEFAULT_USER_ID
        u_date = str(params[1]) if len(params) > 1 else time.strftime("%Y-%m-%d", time.gmtime())
        matches = [
            u for u in data.get("user_daily_token_usage", [])
            if u.get("user_id") == user_id and str(u.get("usage_date")) == u_date
        ]
        return {"rows": matches, "rowCount": len(matches)}

    if "user_daily_token_usage" in sql and ("insert into" in sql or "update" in sql):
        user_id = params[0] if len(params) > 0 else DEFAULT_USER_ID
        u_date = str(params[1]) if len(params) > 1 else time.strftime("%Y-%m-%d", time.gmtime())
        prompt_t = int(params[2]) if len(params) > 2 else 0
        comp_t = int(params[3]) if len(params) > 3 else 0
        tot_t = int(params[4]) if len(params) > 4 else (prompt_t + comp_t)

        records = data.setdefault("user_daily_token_usage", [])
        for r in records:
            if r.get("user_id") == user_id and str(r.get("usage_date")) == u_date:
                r["prompt_tokens"] = r.get("prompt_tokens", 0) + prompt_t
                r["completion_tokens"] = r.get("completion_tokens", 0) + comp_t
                r["total_tokens"] = r.get("total_tokens", 0) + tot_t
                r["updated_at"] = now_iso
                _write_json_db(data)
                return {"rows": [r], "rowCount": 1}

        new_r = {
            "user_id": user_id,
            "usage_date": u_date,
            "prompt_tokens": prompt_t,
            "completion_tokens": comp_t,
            "total_tokens": tot_t,
            "updated_at": now_iso,
        }
        records.append(new_r)
        _write_json_db(data)
        return {"rows": [new_r], "rowCount": 1}

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
                    "008_users_and_multitenancy.sql",
                    "009_memory_recency_and_token_usage.sql",
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

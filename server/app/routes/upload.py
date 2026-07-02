import hashlib
import json
import os
import time
import uuid

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..core import db
from ..core.config import DEFAULT_USER_ID, QDRANT_URL
from ..rag import parse_document, chunk_with_pages, generate_embedding, search_relevant_chunks
from ..retrieval.qdrant_client import upsert_points, COLLECTIONS

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "../../uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

RAG_INDEXABLE_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}

# Extension allowlist as a second line of defense alongside the MIME check —
# content_type is client-supplied and can be spoofed, so we also cap what
# extension a generated filename is allowed to carry on disk.
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".docx", ".png", ".jpg", ".jpeg", ".webp", ".gif"}

MAX_FILE_SIZE = 10 * 1024 * 1024


@router.post("/api/upload", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    body = await file.read()
    if len(body) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    mimetype = file.content_type or "application/octet-stream"
    is_image = mimetype in IMAGE_MIME_TYPES or mimetype.startswith("image/")
    if not is_image and mimetype not in RAG_INDEXABLE_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f'Unsupported file type "{mimetype}". Supported now: PDF, DOCX, TXT, Markdown, CSV, images. '
                "PPTX/Excel support is planned (see ARCHITECTURE.md)."
            ),
        )

    # Path-traversal / malicious-extension guard: derive the extension from
    # only the basename of the client-supplied filename (strips any leading
    # directory components like "../../etc/passwd") and reject anything
    # outside the allowlist — the on-disk filename is otherwise fully
    # server-generated (timestamp + uuid), so this only constrains the
    # trailing extension, but it stops both directory traversal and
    # "upload a .php/.sh with a spoofed content-type" attacks.
    safe_basename = os.path.basename((file.filename or "").replace("\\", "/"))
    ext = os.path.splitext(safe_basename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f'Unsupported file extension "{ext or "(none)"}"')

    filename = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:9]}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    resolved = os.path.realpath(file_path)
    if not resolved.startswith(os.path.realpath(UPLOAD_DIR) + os.sep):
        raise HTTPException(status_code=400, detail="Invalid file path")
    with open(file_path, "wb") as f:
        f.write(body)

    file_hash = hashlib.sha256(body).hexdigest()

    try:
        existing = await db.query(
            """SELECT id, original_filename, mime_type, size_bytes FROM uploaded_files
               WHERE user_id = $1 AND file_hash = $2 AND ingest_status = 'indexed' LIMIT 1""",
            [DEFAULT_USER_ID, file_hash],
        )
        if existing["rows"]:
            os.remove(file_path)
            dup = existing["rows"][0]
            return {
                "success": True,
                "deduplicated": True,
                "file": {"id": dup["id"], "name": dup["original_filename"], "type": dup["mime_type"], "size": dup["size_bytes"]},
            }

        file_result = await db.query(
            """INSERT INTO uploaded_files (message_id, user_id, filename, original_filename, mime_type, size_bytes, file_path, file_hash, ingest_status)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING *""",
            [None, DEFAULT_USER_ID, filename, file.filename, mimetype, len(body), file_path, file_hash, "indexed" if is_image else "processing"],
        )
        file_record = file_result["rows"][0]

        if is_image:
            return {
                "success": True,
                "file": {"id": file_record["id"], "name": file_record["original_filename"], "type": file_record["mime_type"], "size": file_record["size_bytes"]},
            }

        job_result = await db.query("INSERT INTO indexing_jobs (file_id, status) VALUES ($1, 'running') RETURNING id", [file_record["id"]])
        job_id = job_result["rows"][0]["id"]

        parsed = await parse_document(file_path, mimetype)
        chunks = chunk_with_pages(parsed)

        for chunk in chunks:
            content = chunk["content"]
            page_number = chunk["page_number"]
            if not content.strip():
                continue
            embedding = await generate_embedding(content)
            chunk_result = await db.query(
                "INSERT INTO document_chunks (file_id, content, embedding, page_number) VALUES ($1, $2, $3, $4) RETURNING id",
                [file_record["id"], content, json.dumps(embedding), page_number],
            )
            if QDRANT_URL:
                chunk_id = chunk_result["rows"][0]["id"] if chunk_result["rows"] else None
                try:
                    await upsert_points(COLLECTIONS["documents"]["name"], [{
                        "id": chunk_id,
                        "vector": embedding,
                        "payload": {"file_id": file_record["id"], "content": content, "page_number": page_number, "original_filename": file.filename},
                    }])
                except Exception:
                    pass

        await db.query("UPDATE uploaded_files SET ingest_status = 'indexed' WHERE id = $1", [file_record["id"]])
        await db.query("UPDATE indexing_jobs SET status = 'done', updated_at = now() WHERE id = $1", [job_id])

        return {
            "success": True,
            "file": {"id": file_record["id"], "name": file_record["original_filename"], "type": file_record["mime_type"], "size": file_record["size_bytes"]},
        }
    except Exception as err:
        try:
            await db.query("UPDATE uploaded_files SET ingest_status = 'failed' WHERE file_hash = $1 AND user_id = $2", [file_hash, DEFAULT_USER_ID])
            await db.query(
                """UPDATE indexing_jobs SET status = 'failed', error = $1, updated_at = now()
                   WHERE file_id = (SELECT id FROM uploaded_files WHERE file_hash = $2 AND user_id = $3 LIMIT 1)""",
                [str(err), file_hash, DEFAULT_USER_ID],
            )
        except Exception:
            pass
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Failed to index file for RAG: {err}")


class QueryContextBody(BaseModel):
    query: str
    limit: int | None = None


@router.post("/api/chats/{chat_id}/query-context")
async def query_context(chat_id: str, body: QueryContextBody):
    if not body.query:
        raise HTTPException(status_code=400, detail="Query text is required")
    try:
        top_k = body.limit or 3
        relevant_chunks = await search_relevant_chunks(body.query, chat_id, top_k)
        return {
            "success": True,
            "chunks": [
                {"content": c["content"], "similarity": c.get("similarity"), "fileId": c["file_id"]} for c in relevant_chunks
            ],
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve context: {err}")

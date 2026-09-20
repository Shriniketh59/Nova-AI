import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..agents.memory_agent import memory_agent
from ..agents.research_agent import ResearchAgent
from ..core import db
from ..retrieval.vector_store import get_vector_store, vector_store_enabled
from ..middleware.auth_middleware import get_current_user
from ..retrieval.qdrant_client import COLLECTIONS

router = APIRouter()

research_agent = ResearchAgent()


# ---------------------------------------------------------------------------
# POST /api/research — evidence gathering (docs + web) without full agent chat
# ---------------------------------------------------------------------------
class ResearchBody(BaseModel):
    query: str
    chatId: str | None = None


@router.post("/api/research")
async def research(body: ResearchBody, current_user: dict = Depends(get_current_user)):
    if not body.query:
        raise HTTPException(status_code=400, detail="query is required")
    if body.chatId:
        chat_check = await db.query("SELECT id FROM chats WHERE id = $1 AND user_id = $2", [body.chatId, current_user["id"]])
        if not chat_check["rows"]:
            raise HTTPException(status_code=404, detail="Chat not found")

    result = await research_agent.run(body.query, {"chatId": body.chatId, "userId": current_user["id"]})
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error") or "Research failed")
    return result["output"]


# ---------------------------------------------------------------------------
# POST /api/memory — query relevant short/long-term memory directly
# ---------------------------------------------------------------------------
class MemoryBody(BaseModel):
    query: str
    chatId: str | None = None
    topK: int | None = None


@router.post("/api/memory")
async def query_memory(body: MemoryBody, current_user: dict = Depends(get_current_user)):
    if not body.query:
        raise HTTPException(status_code=400, detail="query is required")
    user_id = current_user["id"]
    if body.chatId:
        chat_check = await db.query("SELECT id FROM chats WHERE id = $1 AND user_id = $2", [body.chatId, user_id])
        if not chat_check["rows"]:
            raise HTTPException(status_code=404, detail="Chat not found")

    result = await memory_agent.run(body.query, {"chatId": body.chatId, "userId": user_id, "topK": body.topK or 3})
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error") or "Memory lookup failed")
    return result["output"]


# ---------------------------------------------------------------------------
# GET /api/documents — list all uploaded/indexed documents for the user
# ---------------------------------------------------------------------------
@router.get("/api/documents")
async def list_documents(current_user: dict = Depends(get_current_user)):
    result = await db.query(
        """SELECT id, original_filename AS name, mime_type AS type, size_bytes AS size,
                  ingest_status AS status, created_at
           FROM uploaded_files WHERE user_id = $1 ORDER BY created_at DESC""",
        [current_user["id"]],
    )
    return result["rows"]


# ---------------------------------------------------------------------------
# GET /api/collections — list vector-store collections (Qdrant) if configured
# ---------------------------------------------------------------------------
@router.get("/api/collections")
async def list_collections():
    if not vector_store_enabled():
        return {"enabled": False, "collections": []}
    return {
        "enabled": True,
        "collections": [{"key": key, **meta} for key, meta in COLLECTIONS.items()],
    }


# ---------------------------------------------------------------------------
# DELETE /api/document/{id} — remove a document, its chunks, and its file
# ---------------------------------------------------------------------------
@router.delete("/api/document/{file_id}")
async def delete_document(file_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user["id"]
    existing = await db.query(
        "SELECT * FROM uploaded_files WHERE id = $1 AND user_id = $2", [file_id, user_id]
    )
    if not existing["rows"]:
        raise HTTPException(status_code=404, detail="Document not found")
    record = existing["rows"][0]

    await db.query("DELETE FROM uploaded_files WHERE id = $1 AND user_id = $2", [file_id, user_id])

    file_path = record.get("file_path")
    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass

    if vector_store_enabled():
        try:
            store = get_vector_store()
            await store.delete(COLLECTIONS["documents"]["name"], filter={"must": [{"key": "file_id", "match": {"value": file_id}}]})
        except Exception:
            pass

    return {"message": "Document deleted successfully"}

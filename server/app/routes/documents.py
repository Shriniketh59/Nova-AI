"""Thin document-management + capability endpoints that were only reachable
through the streaming chat routes before. These call the same
agents/services chat_query() already uses — no logic duplication, just a
direct (non-streaming) REST surface for: compare, summarize, research,
memory, and document/collection management."""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents.document_analysis_agent import DocumentAnalysisAgent
from ..agents.document_comparison_agent import DocumentComparisonAgent
from ..agents.memory_agent import memory_agent
from ..agents.research_agent import ResearchAgent
from ..core import db
from ..core.config import DEFAULT_USER_ID, QDRANT_URL
from ..retrieval.qdrant_client import COLLECTIONS

router = APIRouter()

document_analysis_agent = DocumentAnalysisAgent()
document_comparison_agent = DocumentComparisonAgent()
research_agent = ResearchAgent()


# ---------------------------------------------------------------------------
# POST /api/compare — compare two+ uploaded documents in a chat
# ---------------------------------------------------------------------------
class CompareBody(BaseModel):
    chatId: str
    query: str | None = None


@router.post("/api/compare")
async def compare_documents(body: CompareBody):
    chunks = await db.query(
        """SELECT dc.content, dc.file_id, uf.original_filename
           FROM document_chunks dc JOIN uploaded_files uf ON uf.id = dc.file_id
           WHERE uf.message_id IN (SELECT id FROM messages WHERE chat_id = $1)""",
        [body.chatId],
    )
    by_file: dict = {}
    for c in chunks["rows"]:
        entry = by_file.setdefault(c["file_id"], {"fileName": c["original_filename"], "text": ""})
        entry["text"] += f"{c['content']}\n"
    documents = list(by_file.values())
    if len(documents) < 2:
        raise HTTPException(status_code=400, detail="At least two uploaded documents are required to compare")

    result = await document_comparison_agent.run(body.query or "Compare these documents.", {"documents": documents})
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error") or "Comparison failed")
    return result["output"]


# ---------------------------------------------------------------------------
# POST /api/summarize — summarize an uploaded document (or arbitrary text)
# ---------------------------------------------------------------------------
class SummarizeBody(BaseModel):
    chatId: str | None = None
    fileId: str | None = None
    text: str | None = None


@router.post("/api/summarize")
async def summarize(body: SummarizeBody):
    if body.text:
        document_text, file_name = body.text, "provided text"
    elif body.fileId:
        chunks = await db.query(
            """SELECT dc.content, uf.original_filename FROM document_chunks dc
               JOIN uploaded_files uf ON uf.id = dc.file_id WHERE dc.file_id = $1""",
            [body.fileId],
        )
        if not chunks["rows"]:
            raise HTTPException(status_code=404, detail="File not found or has no indexed content")
        document_text = "\n".join(c["content"] for c in chunks["rows"])
        file_name = chunks["rows"][0]["original_filename"]
    elif body.chatId:
        chunks = await db.query(
            """SELECT dc.content, uf.original_filename FROM document_chunks dc
               JOIN uploaded_files uf ON uf.id = dc.file_id
               WHERE uf.message_id IN (SELECT id FROM messages WHERE chat_id = $1)""",
            [body.chatId],
        )
        if not chunks["rows"]:
            raise HTTPException(status_code=404, detail="No indexed documents found in this chat")
        document_text = "\n".join(c["content"] for c in chunks["rows"])
        file_name = chunks["rows"][0]["original_filename"]
    else:
        raise HTTPException(status_code=400, detail="One of text, fileId or chatId is required")

    result = await document_analysis_agent.run("Summarize this document.", {"documentText": document_text, "fileName": file_name})
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error") or "Summarization failed")
    return result["output"]


# ---------------------------------------------------------------------------
# POST /api/research — evidence gathering (docs + web) without full agent chat
# ---------------------------------------------------------------------------
class ResearchBody(BaseModel):
    query: str
    chatId: str | None = None


@router.post("/api/research")
async def research(body: ResearchBody):
    if not body.query:
        raise HTTPException(status_code=400, detail="query is required")
    result = await research_agent.run(body.query, {"chatId": body.chatId})
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
async def query_memory(body: MemoryBody):
    if not body.query:
        raise HTTPException(status_code=400, detail="query is required")
    result = await memory_agent.run(body.query, {"chatId": body.chatId, "topK": body.topK or 3})
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error") or "Memory lookup failed")
    return result["output"]


# ---------------------------------------------------------------------------
# GET /api/documents — list all uploaded/indexed documents for the user
# ---------------------------------------------------------------------------
@router.get("/api/documents")
async def list_documents():
    result = await db.query(
        """SELECT id, original_filename AS name, mime_type AS type, size_bytes AS size,
                  ingest_status AS status, created_at
           FROM uploaded_files WHERE user_id = $1 ORDER BY created_at DESC""",
        [DEFAULT_USER_ID],
    )
    return result["rows"]


# ---------------------------------------------------------------------------
# GET /api/collections — list vector-store collections (Qdrant) if configured
# ---------------------------------------------------------------------------
@router.get("/api/collections")
async def list_collections():
    if not QDRANT_URL:
        return {"enabled": False, "collections": []}
    return {
        "enabled": True,
        "collections": [{"key": key, **meta} for key, meta in COLLECTIONS.items()],
    }


# ---------------------------------------------------------------------------
# DELETE /api/document/{id} — remove a document, its chunks, and its file
# ---------------------------------------------------------------------------
@router.delete("/api/document/{file_id}")
async def delete_document(file_id: str):
    existing = await db.query(
        "SELECT * FROM uploaded_files WHERE id = $1 AND user_id = $2", [file_id, DEFAULT_USER_ID]
    )
    if not existing["rows"]:
        raise HTTPException(status_code=404, detail="Document not found")
    record = existing["rows"][0]

    await db.query("DELETE FROM uploaded_files WHERE id = $1 AND user_id = $2", [file_id, DEFAULT_USER_ID])

    file_path = record.get("file_path")
    if file_path and os.path.isfile(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass

    if QDRANT_URL:
        try:
            from ..retrieval.vector_store import get_vector_store

            store = get_vector_store()
            await store.delete(COLLECTIONS["documents"]["name"], filter={"must": [{"key": "file_id", "match": {"value": file_id}}]})
        except Exception:
            pass

    return {"message": "Document deleted successfully"}

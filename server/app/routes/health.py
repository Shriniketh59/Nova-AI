from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core import db
from ..core.config import QDRANT_URL
from ..retrieval.qdrant_client import ensure_all_collections

router = APIRouter()


@router.get("/api/v1/health")
async def health():
    """Contract mirrors sret-rag's GET /api/v1/health: {status, index_ready, model}."""
    result = {"status": "ok", "db": "unknown", "qdrant": "unknown" if QDRANT_URL else "disabled"}
    try:
        await db.query("SELECT 1")
        result["db"] = "ok"
    except Exception:
        result["db"] = "error"
        result["status"] = "degraded"

    if QDRANT_URL:
        try:
            await ensure_all_collections()
            result["qdrant"] = "ok"
        except Exception:
            result["qdrant"] = "error"
            result["status"] = "degraded"

    return JSONResponse(content=result, status_code=200 if result["status"] == "ok" else 503)

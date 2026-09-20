from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..core import db
from ..core.config import VECTOR_STORE_BACKEND
from ..core.startup_checks import check_ollama_models, ensure_vector_store_ready
from ..retrieval.vector_store import vector_store_enabled

router = APIRouter()


@router.get("/health")
@router.get("/api/health")
@router.get("/api/v1/health")
async def health():
    """Contract mirrors sret-rag's GET /api/v1/health: {status, index_ready, model}."""
    vector_enabled = vector_store_enabled()
    result = {
        "status": "ok",
        "db": "unknown",
        "vector_store": {
            "backend": VECTOR_STORE_BACKEND,
            "state": "unknown" if vector_enabled else "disabled",
        },
        # Kept for backwards compatibility with existing clients/tests.
        "qdrant": "unknown" if VECTOR_STORE_BACKEND == "qdrant" and vector_enabled else "disabled",
    }
    try:
        await db.query("SELECT 1")
        result["db"] = "ok"
    except Exception:
        result["db"] = "error"
        result["status"] = "degraded"

    if vector_enabled:
        ok = await ensure_vector_store_ready()
        result["vector_store"]["state"] = "ok" if ok else "error"
        if VECTOR_STORE_BACKEND == "qdrant":
            result["qdrant"] = "ok" if ok else "error"
        if not ok:
            result["status"] = "degraded"

    # Local model availability (never substitutes a model, just reports).
    models = await check_ollama_models()
    result["ollama"] = {
        "reachable": models.get("reachable", False),
        "missing_models": models.get("missing", []),
    }
    if not models.get("reachable") or models.get("missing"):
        result["status"] = "degraded"

    return JSONResponse(content=result, status_code=200 if result["status"] == "ok" else 503)

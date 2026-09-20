"""Startup preflight checks.

These verify that the *local* dependencies Nova needs are actually present, and
report loudly (rather than failing silently at the first user request) when
they are not. Nothing here reaches an external AI service — it only talks to
the local Ollama daemon and the local vector store.
"""

import httpx

from ..core.config import (
    OLLAMA_CODE_MODEL,
    OLLAMA_EMBED_MODEL,
    OLLAMA_MODEL,
    OLLAMA_URL,
    VECTOR_STORE_BACKEND,
)
from ..core.logger import logger

# Populated by check_ollama_models() so /health can report it without re-probing.
ollama_status: dict = {"checked": False, "reachable": False, "missing": [], "available": []}


def _model_present(requested: str, available: list[str]) -> bool:
    """Ollama tags are `name:tag`; treat a bare `name` as matching `name:latest`."""
    if requested in available:
        return True
    wanted = requested if ":" in requested else f"{requested}:latest"
    return wanted in available


async def check_ollama_models() -> dict:
    """Verify the configured Ollama models are actually installed.

    Logs an explicit error naming each missing model (and the `ollama pull`
    needed to fix it) instead of silently substituting a different model.
    """
    required = {
        "chat": OLLAMA_MODEL,
        "embeddings": OLLAMA_EMBED_MODEL,
        "code": OLLAMA_CODE_MODEL,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{OLLAMA_URL}/api/tags")
            res.raise_for_status()
            available = [m.get("name", "") for m in (res.json().get("models") or [])]
    except Exception as err:
        ollama_status.update({
            "checked": True,
            "reachable": False,
            "error": str(err),
            "missing": sorted(set(required.values())),
            "available": [],
        })
        logger.error(
            "startup.ollama_unreachable",
            {
                "url": OLLAMA_URL,
                "error": str(err),
                "hint": "Start the local model server with `ollama serve`.",
            },
        )
        return ollama_status

    missing = {role: name for role, name in required.items() if not _model_present(name, available)}
    ollama_status.update({
        "checked": True,
        "reachable": True,
        "available": available,
        "missing": sorted(set(missing.values())),
    })

    if missing:
        logger.error(
            "startup.ollama_model_missing",
            {
                "missing": missing,
                "available": available,
                "hint": "Install them with: "
                        + "; ".join(f"ollama pull {name}" for name in sorted(set(missing.values())))
                        + ". Nova will NOT substitute a different model.",
            },
        )
    else:
        logger.info("startup.ollama_models_ready", {"models": sorted(set(required.values()))})

    return ollama_status


async def ensure_vector_store_ready() -> bool:
    """Create the configured backend's collections. Returns True on success."""
    from ..retrieval.qdrant_client import COLLECTIONS
    from ..retrieval.vector_store import get_vector_store, vector_store_enabled

    if not vector_store_enabled():
        logger.warn(
            "startup.vector_store_disabled",
            {
                "backend": VECTOR_STORE_BACKEND,
                "hint": "Qdrant needs QDRANT_URL set; the default `chroma` backend needs none.",
            },
        )
        return False

    try:
        store = get_vector_store()
        for collection in COLLECTIONS.values():
            await store.ensure_collection(collection)
        logger.info("startup.vector_store_ready", {"backend": VECTOR_STORE_BACKEND})
        return True
    except Exception as err:
        logger.warn(
            "startup.vector_store_unavailable",
            {"backend": VECTOR_STORE_BACKEND, "error": str(err),
             "hint": "Retrieval will fall back to in-Python cosine search."},
        )
        return False

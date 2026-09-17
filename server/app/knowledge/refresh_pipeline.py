import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from ..core import db
from ..core.config import QDRANT_URL
from ..core.logger import logger
from ..rag import generate_embedding
from ..retrieval.qdrant_client import COLLECTIONS, upsert_points
from ..retrieval.vector_store import get_vector_store
from .cleaning import clean_content, compute_content_hash, validate_document_quality
from .chunking import split_structured_text
from .document_schema import (
    Document,
    DocumentChunk,
    DocumentMetadata,
    calculate_freshness_score,
    extract_domain,
    utc_now_iso,
)

# Configurable refresh intervals (in seconds)
DEFAULT_REFRESH_INTERVALS = {
    "hourly": 3600,
    "6hour": 21600,
    "daily": 86400,
    "weekly": 604800,
}


class DataRefreshManager:
    """Manages document freshness, scheduled/manual refreshes, content hash-based
    deduplication, conditional HTTP fetching, and vector store synchronization."""

    def __init__(self):
        self._sources: Dict[str, Dict[str, Any]] = {}
        self._documents: Dict[str, Document] = {}  # In-memory registry / fast lookup
        self._refresh_task: Optional[asyncio.Task] = None
        self._running = False

    def register_source(
        self,
        source_id: str,
        source_url: str,
        refresh_interval_s: int = 86400,
        source_type: str = "web",
        category: str = "general",
        title: str = "",
    ):
        """Registers an external knowledge source with its own refresh interval."""
        self._sources[source_id] = {
            "source_id": source_id,
            "source_url": source_url,
            "refresh_interval_s": refresh_interval_s,
            "source_type": source_type,
            "category": category,
            "title": title or source_id,
            "last_refreshed_at": None,
            "etag": None,
            "last_modified": None,
            "content_hash": None,
            "document_version": 0,
        }
        logger.info("refresh_manager.registered_source", {"sourceId": source_id, "interval": refresh_interval_s})

    async def fetch_source_content(self, source_info: dict) -> tuple[Optional[str], Optional[str], Optional[str], bool]:
        """Performs conditional HTTP request using ETag and If-Modified-Since.
        Returns: (content, etag, last_modified, not_modified)"""
        url = source_info.get("source_url")
        if not url or not url.startswith(("http://", "https://")):
            return None, None, None, False

        headers = {"User-Agent": "NovaAI-KnowledgeBot/1.0"}
        if source_info.get("etag"):
            headers["If-None-Match"] = source_info["etag"]
        if source_info.get("last_modified"):
            headers["If-Modified-Since"] = source_info["last_modified"]

        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 304:
                    return None, source_info.get("etag"), source_info.get("last_modified"), True
                if res.status_code >= 400:
                    logger.warn("refresh_manager.fetch_failed", {"url": url, "status": res.status_code})
                    return None, None, None, False

                new_etag = res.headers.get("ETag")
                new_last_modified = res.headers.get("Last-Modified")
                return res.text, new_etag, new_last_modified, False
        except Exception as err:
            logger.error("refresh_manager.fetch_error", {"url": url, "error": str(err)})
            return None, None, None, False

    async def ingest_or_update(
        self,
        source_id: str,
        content: str,
        title: str = "",
        source_url: str | None = None,
        source_type: str = "file",
        category: str = "general",
        published_at: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        force_reindex: bool = False,
        user_id: str | None = None,
        **kwargs,
    ) -> dict:
        """Core Ingestion Pipeline:
        FETCH -> NORMALIZE -> CLEAN -> CONTENT HASH -> CHECK EXISTING
        If UNCHANGED: Skip re-embedding.
        If CHANGED: Increment version, re-chunk, re-embed, update vector DB points without duplicate records."""
        is_valid, validation_msg = validate_document_quality(content, source_id)
        if not is_valid:
            logger.warn("refresh_manager.quality_rejected", {"sourceId": source_id, "reason": validation_msg})
            return {"status": "rejected", "reason": validation_msg, "reembedded": False}

        cleaned = clean_content(content)
        new_hash = compute_content_hash(cleaned)

        existing_doc = self._documents.get(source_id)

        # 1. Content Hash Check: skip if content has not changed
        if existing_doc and existing_doc.metadata.content_hash == new_hash and not force_reindex:
            existing_doc.metadata.fetched_at = utc_now_iso()
            existing_doc.metadata.freshness_score = calculate_freshness_score(existing_doc.metadata.published_at or existing_doc.metadata.updated_at)
            logger.info("refresh_manager.unchanged_skip", {"sourceId": source_id, "hash": new_hash})
            return {
                "status": "unchanged",
                "document_id": source_id,
                "reembedded": False,
                "version": existing_doc.metadata.document_version,
                "chunks_count": len(existing_doc.chunks),
            }

        # 2. Changed or New Document: prepare chunks and metadata
        current_version = (existing_doc.metadata.document_version + 1) if existing_doc else 1
        meta = DocumentMetadata(
            document_id=source_id,
            source_url=source_url,
            source_domain=extract_domain(source_url),
            title=title or (existing_doc.metadata.title if existing_doc else source_id),
            content_hash=new_hash,
            document_version=current_version,
            created_at=existing_doc.metadata.created_at if existing_doc else utc_now_iso(),
            updated_at=utc_now_iso(),
            fetched_at=utc_now_iso(),
            published_at=published_at or (existing_doc.metadata.published_at if existing_doc else None),
            source_type=source_type,
            category=category,
            freshness_score=calculate_freshness_score(published_at or utc_now_iso()),
            etag=etag,
            last_modified_header=last_modified,
        )

        chunks = split_structured_text(cleaned, target_size=750, max_size=1000, overlap=100, document_id=source_id)
        if not chunks:
            return {"status": "error", "reason": "No valid chunks produced", "reembedded": False}

        # 3. Embed chunks (with graceful resilience if embedding service is offline)
        points_to_upsert = []
        for chunk in chunks:
            try:
                chunk_embedding = await generate_embedding(chunk.content)
            except Exception as err:
                logger.warn("refresh_manager.embed_chunk_failed", {"error": str(err)})
                chunk_embedding = None
            chunk.embedding = chunk_embedding
            chunk.metadata = {
                "document_id": source_id,
                "title": meta.title,
                "source_url": meta.source_url,
                "source_domain": meta.source_domain,
                "source_type": meta.source_type,
                "category": meta.category,
                "document_version": meta.document_version,
                "section_heading": chunk.section_heading,
                "freshness_score": meta.freshness_score,
                "updated_at": meta.updated_at,
                "content_hash": chunk.content_hash,
            }

            if QDRANT_URL:
                points_to_upsert.append({
                    "id": chunk.chunk_id,
                    "vector": chunk_embedding,
                    "payload": {
                        "content": chunk.content,
                        "file_id": source_id,
                        "document_id": source_id,
                        "original_filename": meta.title,
                        **chunk.metadata,
                    },
                })

        # 4. Clean up existing vectors for this document in Qdrant if updating
        if existing_doc and QDRANT_URL:
            try:
                store = get_vector_store()
                await store.delete(
                    COLLECTIONS["documents"]["name"],
                    filter={"must": [{"key": "document_id", "match": {"value": source_id}}]},
                )
            except Exception as err:
                logger.warn("refresh_manager.qdrant_delete_failed", {"error": str(err)})

        # 5. Upsert new points into Qdrant
        if points_to_upsert and QDRANT_URL:
            try:
                await upsert_points(COLLECTIONS["documents"]["name"], points_to_upsert)
            except Exception as err:
                logger.error("refresh_manager.qdrant_upsert_failed", {"error": str(err)})

        # Store in document registry
        new_doc = Document(metadata=meta, raw_content=content, cleaned_content=cleaned, chunks=chunks)
        self._documents[source_id] = new_doc

        logger.info(
            "refresh_manager.indexed",
            {"sourceId": source_id, "version": current_version, "chunks": len(chunks), "hash": new_hash},
        )
        return {
            "status": "updated" if existing_doc else "created",
            "document_id": source_id,
            "reembedded": True,
            "version": current_version,
            "chunks_count": len(chunks),
        }

    async def refresh_source(self, source_id: str, force_reindex: bool = False) -> dict:
        """Refreshes a specific source by fetching its content and running through the pipeline."""
        source_info = self._sources.get(source_id)
        if not source_info:
            return {"status": "not_found", "reason": f"Source {source_id} not registered"}

        content, new_etag, new_last_modified, not_modified = await self.fetch_source_content(source_info)
        now_iso = utc_now_iso()
        source_info["last_refreshed_at"] = now_iso

        if not_modified:
            logger.info("refresh_manager.not_modified_304", {"sourceId": source_id})
            return {"status": "unchanged", "reembedded": False, "reason": "HTTP 304 Not Modified"}

        if not content:
            return {"status": "error", "reason": "Failed to fetch source content"}

        result = await self.ingest_or_update(
            source_id=source_id,
            content=content,
            title=source_info.get("title", source_id),
            source_url=source_info.get("source_url"),
            source_type=source_info.get("source_type", "web"),
            category=source_info.get("category", "general"),
            etag=new_etag,
            last_modified=new_last_modified,
            force_reindex=force_reindex,
        )

        if result.get("status") in ("created", "updated", "unchanged"):
            source_info["etag"] = new_etag
            source_info["last_modified"] = new_last_modified
            source_info["content_hash"] = self._documents[source_id].metadata.content_hash
            source_info["document_version"] = self._documents[source_id].metadata.document_version

        return result

    async def refresh_due_sources(self) -> dict:
        """Checks all registered sources and refreshes those whose refresh interval has elapsed."""
        now = time.time()
        refreshed_count = 0
        results = {}

        for s_id, s_info in self._sources.items():
            last_dt_str = s_info.get("last_refreshed_at")
            interval = s_info.get("refresh_interval_s", 86400)

            is_due = False
            if not last_dt_str:
                is_due = True
            else:
                try:
                    last_time = datetime.fromisoformat(last_dt_str.replace("Z", "+00:00")).timestamp()
                    if now - last_time >= interval:
                        is_due = True
                except Exception:
                    is_due = True

            if is_due:
                res = await self.refresh_source(s_id)
                results[s_id] = res
                refreshed_count += 1

        return {"refreshed_count": refreshed_count, "results": results}

    async def full_reindex(self) -> dict:
        """Re-indexes all registered sources forcefully."""
        results = {}
        for s_id in list(self._sources.keys()):
            results[s_id] = await self.refresh_source(s_id, force_reindex=True)
        return {"reindexed_count": len(results), "results": results}

    def get_document(self, document_id: str) -> Optional[Document]:
        return self._documents.get(document_id)

    def list_documents(self) -> List[dict]:
        return [doc.metadata.to_dict() for doc in self._documents.values()]

    def list_all_chunks(self) -> List[dict]:
        all_chunks = []
        for doc in self._documents.values():
            for c in doc.chunks:
                all_chunks.append({
                    "id": c.chunk_id,
                    "document_id": c.document_id,
                    "content": c.content,
                    "embedding": c.embedding,
                    "page_number": c.page_number,
                    "section_heading": c.section_heading,
                    "original_filename": doc.metadata.title,
                    "title": doc.metadata.title,
                    "source_url": doc.metadata.source_url,
                    "source_domain": doc.metadata.source_domain,
                    "source_type": doc.metadata.source_type,
                    "category": doc.metadata.category,
                    "freshness_score": doc.metadata.freshness_score,
                    "updated_at": doc.metadata.updated_at,
                })
        return all_chunks


# Global singleton instance
refresh_manager = DataRefreshManager()

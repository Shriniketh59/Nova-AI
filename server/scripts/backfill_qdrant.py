"""One-off migration: push existing document_chunks rows (created before
Qdrant was wired in) into the nova_documents collection. Safe to re-run —
upsert_points overwrites by id.

Usage: python -m scripts.backfill_qdrant  (run from server/ with QDRANT_URL set)
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core import db
from app.core.config import QDRANT_URL
from app.retrieval.qdrant_client import ensure_all_collections, upsert_points, COLLECTIONS

BATCH_SIZE = 100


async def main():
    if not QDRANT_URL:
        print("QDRANT_URL not set — point it at your Qdrant instance first.")
        sys.exit(1)

    await db.init_db()
    await ensure_all_collections()

    chunks_res = await db.query("SELECT * FROM document_chunks", [])
    files_res = await db.query("SELECT id, original_filename FROM uploaded_files", [])
    filename_by_file_id = {f["id"]: f["original_filename"] for f in files_res["rows"]}

    chunks = chunks_res["rows"]
    print(f"Backfilling {len(chunks)} chunks into Qdrant...")

    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        points = [
            {
                "id": chunk["id"],
                "vector": chunk["embedding"] if isinstance(chunk["embedding"], list) else json.loads(chunk["embedding"]),
                "payload": {
                    "file_id": chunk["file_id"],
                    "content": chunk["content"],
                    "page_number": chunk.get("page_number"),
                    "original_filename": filename_by_file_id.get(chunk["file_id"], "unknown document"),
                },
            }
            for chunk in batch
        ]
        await upsert_points(COLLECTIONS["documents"]["name"], points)
        print(f"  {min(i + BATCH_SIZE, len(chunks))}/{len(chunks)}")

    print("Backfill complete.")
    await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())

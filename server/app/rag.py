import re

import httpx
from pypdf import PdfReader
from docx import Document as DocxDocument

from .core import db
from .core.config import OLLAMA_URL, OLLAMA_EMBED_MODEL
from .core.logger import logger
from .jobs.cache import get_cached_embedding, set_cached_embedding

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


async def generate_embedding(text: str) -> list[float]:
    """Embeds text via local Ollama. Cached — the same text (a repeated chunk
    on re-upload, a repeated query) always embeds to the same vector, so a
    cache hit skips the Ollama round-trip entirely."""
    cached = get_cached_embedding(text)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": OLLAMA_EMBED_MODEL, "prompt": text},
            )
            res.raise_for_status()
            data = res.json()
            embedding = data["embedding"]
            set_cached_embedding(text, embedding)
            return embedding
    except Exception as err:
        logger.error("Embedding generation error", {"error": str(err)})
        raise


def chunk_text(text: str, chunk_size: int = 800, chunk_overlap: int = 150) -> list[str]:
    """Chunk text preserving paragraph/sentence boundaries."""
    if not text:
        return []
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_chunk = ""

    for paragraph in paragraphs:
        trimmed_paragraph = paragraph.strip()
        if not trimmed_paragraph:
            continue

        if len(current_chunk + "\n\n" + trimmed_paragraph) <= chunk_size:
            current_chunk = current_chunk + "\n\n" + trimmed_paragraph if current_chunk else trimmed_paragraph
        else:
            if current_chunk:
                chunks.append(current_chunk)

            if len(trimmed_paragraph) > chunk_size:
                sentences = SENTENCE_SPLIT_RE.split(trimmed_paragraph)
                temp_chunk = ""
                for sentence in sentences:
                    trimmed_sentence = sentence.strip()
                    if not trimmed_sentence:
                        continue
                    if len(temp_chunk + " " + trimmed_sentence) <= chunk_size:
                        temp_chunk = temp_chunk + " " + trimmed_sentence if temp_chunk else trimmed_sentence
                    else:
                        if temp_chunk:
                            chunks.append(temp_chunk)
                        temp_chunk = trimmed_sentence
                current_chunk = temp_chunk
            else:
                current_chunk = trimmed_paragraph

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


async def parse_document(file_path: str, mime_type: str) -> dict:
    """Parse document text based on mime-type. PDFs return {text, pages} so
    chunking can stamp each chunk with the real page number for source
    grounding citations — other formats have no page concept, pages stays None."""
    try:
        if mime_type == "application/pdf":
            reader = PdfReader(file_path)
            pages = [page.extract_text() or "" for page in reader.pages]
            return {"text": "\n\n".join(pages), "pages": pages}
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            doc = DocxDocument(file_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            return {"text": text, "pages": None}
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                return {"text": f.read(), "pages": None}
    except Exception as err:
        logger.error(f"Error parsing file {file_path}", {"error": str(err)})
        raise


def chunk_with_pages(parsed: dict, chunk_size: int = 800, chunk_overlap: int = 150) -> list[dict]:
    """Chunks each page separately when page text is available, stamping every
    chunk with its real page_number — falls back to whole-text chunking
    (page_number None) for formats without pages."""
    if not parsed.get("pages"):
        return [{"content": c, "page_number": None} for c in chunk_text(parsed["text"], chunk_size, chunk_overlap)]

    out = []
    for idx, page_text in enumerate(parsed["pages"]):
        for content in chunk_text(page_text, chunk_size, chunk_overlap):
            out.append({"content": content, "page_number": idx + 1})
    return out


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot_product = 0.0
    norm_a = 0.0
    norm_b = 0.0
    length = min(len(vec_a), len(vec_b))
    for i in range(length):
        dot_product += vec_a[i] * vec_b[i]
        norm_a += vec_a[i] * vec_a[i]
        norm_b += vec_b[i] * vec_b[i]
    if norm_a == 0 or norm_b == 0:
        return 0
    return dot_product / ((norm_a ** 0.5) * (norm_b ** 0.5))


async def fetch_chunks_for_chat(chat_id: str) -> list[dict]:
    """Fetches every document chunk belonging to files uploaded in a chat
    session, without scoring. Shared by semantic search (cosine) and keyword
    search (BM25-lite) so both passes of hybrid search hit the same candidate pool."""
    messages_res = await db.query("SELECT id FROM messages WHERE chat_id = $1", [chat_id])
    if messages_res["rowCount"] == 0:
        return []
    message_ids = [m["id"] for m in messages_res["rows"]]

    files_res = await db.query(
        "SELECT id, original_filename FROM uploaded_files WHERE message_id = ANY($1::uuid[])",
        [message_ids],
    )
    if files_res["rowCount"] == 0:
        return []

    file_ids = [f["id"] for f in files_res["rows"]]
    filename_by_file_id = {f["id"]: f["original_filename"] for f in files_res["rows"]}

    chunks_res = await db.query(
        "SELECT * FROM document_chunks WHERE file_id = ANY($1::uuid[])",
        [file_ids],
    )
    if chunks_res["rowCount"] == 0:
        return []

    return [
        {**chunk, "original_filename": filename_by_file_id.get(chunk["file_id"], "unknown document")}
        for chunk in chunks_res["rows"]
    ]


async def fetch_file_ids_for_chat(chat_id: str) -> list[str]:
    messages_res = await db.query("SELECT id FROM messages WHERE chat_id = $1", [chat_id])
    if messages_res["rowCount"] == 0:
        return []
    message_ids = [m["id"] for m in messages_res["rows"]]
    files_res = await db.query(
        "SELECT id FROM uploaded_files WHERE message_id = ANY($1::uuid[])",
        [message_ids],
    )
    return [f["id"] for f in files_res["rows"]]


async def fetch_images_for_chat(chat_id: str) -> list[dict]:
    """Image uploads skip chunking/embedding (see /api/upload), so the routing
    engine needs a separate lookup to know "this chat has an attached image" —
    same message_id join as fetch_chunks_for_chat, just filtered to image/* mime."""
    messages_res = await db.query("SELECT id FROM messages WHERE chat_id = $1", [chat_id])
    if messages_res["rowCount"] == 0:
        return []
    message_ids = [m["id"] for m in messages_res["rows"]]
    files_res = await db.query(
        "SELECT id, original_filename, mime_type, file_path FROM uploaded_files "
        "WHERE message_id = ANY($1::uuid[]) AND mime_type LIKE 'image/%'",
        [message_ids],
    )
    return files_res["rows"]


async def search_relevant_chunks(query_text: str, chat_id: str, top_k: int = 3) -> list[dict]:
    try:
        query_vector = await generate_embedding(query_text)
        chunks = await fetch_chunks_for_chat(chat_id)
        if not chunks:
            return []

        chunks_with_similarity = [
            {**chunk, "similarity": cosine_similarity(query_vector, chunk["embedding"])} for chunk in chunks
        ]
        chunks_with_similarity.sort(key=lambda c: c["similarity"], reverse=True)
        return chunks_with_similarity[:top_k]
    except Exception as err:
        logger.error("Error searching relevant chunks", {"error": str(err)})
        return []

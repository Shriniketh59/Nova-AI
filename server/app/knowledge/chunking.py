import hashlib
import re
from typing import List
from .document_schema import DocumentChunk

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
HEADING_RE = re.compile(r"^(#{1,6}\s+.+|[A-Z0-9\s_-]{3,50}:)$", re.M)


def _chunk_hash(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def _extract_body(sec_lines: list[str]) -> str:
    body_lines = [l for l in sec_lines if not HEADING_RE.match(l.strip())]
    return "\n".join(body_lines).strip()


def split_structured_text(
    text: str,
    target_size: int = 750,
    max_size: int = 1000,
    overlap: int = 100,
    document_id: str = "",
) -> List[DocumentChunk]:
    """Splits text into chunks respecting markdown headings, code blocks, lists,
    paragraphs, and sentence boundaries. Deduplicates identical body chunks across sections."""
    if not text or not text.strip():
        return []

    lines = text.split("\n")
    sections: list[tuple[str | None, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    in_code_fence = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            current_lines.append(line)
            continue

        if not in_code_fence and HEADING_RE.match(stripped):
            if current_lines:
                sections.append((current_heading, current_lines))
                current_lines = []
            current_heading = stripped.lstrip("#").strip()
            current_lines.append(line)
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, current_lines))

    chunks: List[DocumentChunk] = []
    seen_hashes = set()
    chunk_index = 0

    for heading, sec_lines in sections:
        sec_text = "\n".join(sec_lines).strip()
        if not sec_text:
            continue

        body_text = _extract_body(sec_lines)
        hash_key = _chunk_hash(body_text if body_text else sec_text)

        # Skip duplicate body text across sections
        if hash_key in seen_hashes:
            continue

        # If section is small enough, keep as single chunk
        if len(sec_text) <= max_size:
            if len(sec_text) >= 20:
                seen_hashes.add(hash_key)
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{document_id}_{chunk_index}",
                        document_id=document_id,
                        content=sec_text,
                        chunk_index=chunk_index,
                        content_hash=hash_key,
                        section_heading=heading,
                    )
                )
                chunk_index += 1
            continue

        # Section is larger, split by double newlines (paragraphs)
        paragraphs = sec_text.split("\n\n")
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 2 <= target_size:
                current_chunk = (current_chunk + "\n\n" + para) if current_chunk else para
            else:
                if current_chunk:
                    ch_hash = _chunk_hash(current_chunk)
                    if ch_hash not in seen_hashes and len(current_chunk) >= 20:
                        seen_hashes.add(ch_hash)
                        chunks.append(
                            DocumentChunk(
                                chunk_id=f"{document_id}_{chunk_index}",
                                document_id=document_id,
                                content=current_chunk,
                                chunk_index=chunk_index,
                                content_hash=ch_hash,
                                section_heading=heading,
                            )
                        )
                        chunk_index += 1

                # If paragraph itself is longer than target_size, break by sentence
                if len(para) > target_size:
                    sentences = SENTENCE_RE.split(para)
                    temp_buf = ""
                    for s in sentences:
                        s = s.strip()
                        if not s:
                            continue
                        if len(temp_buf) + len(s) + 1 <= target_size:
                            temp_buf = (temp_buf + " " + s) if temp_buf else s
                        else:
                            if temp_buf:
                                ch_hash = _chunk_hash(temp_buf)
                                if ch_hash not in seen_hashes and len(temp_buf) >= 20:
                                    seen_hashes.add(ch_hash)
                                    chunks.append(
                                        DocumentChunk(
                                            chunk_id=f"{document_id}_{chunk_index}",
                                            document_id=document_id,
                                            content=temp_buf,
                                            chunk_index=chunk_index,
                                            content_hash=ch_hash,
                                            section_heading=heading,
                                        )
                                    )
                                    chunk_index += 1
                            temp_buf = s
                    current_chunk = temp_buf
                else:
                    current_chunk = para

        if current_chunk:
            ch_hash = _chunk_hash(current_chunk)
            if ch_hash not in seen_hashes and len(current_chunk) >= 20:
                seen_hashes.add(ch_hash)
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{document_id}_{chunk_index}",
                        document_id=document_id,
                        content=current_chunk,
                        chunk_index=chunk_index,
                        content_hash=ch_hash,
                        section_heading=heading,
                    )
                )
                chunk_index += 1

    return chunks

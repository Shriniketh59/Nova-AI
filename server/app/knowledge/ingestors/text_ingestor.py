from ..base_ingestor import BaseIngestor
from ...rag import parse_document, chunk_text


class TextIngestor(BaseIngestor):
    """Real implementation for txt/markdown — same chunker, no page concept."""

    def __init__(self):
        super().__init__("document")

    async def ingest(self, source: dict) -> list[dict]:
        parsed = await parse_document(source["filePath"], source.get("mimeType", "text/plain"))
        chunks = chunk_text(parsed["text"])
        return [{"content": c, "metadata": {}} for c in chunks]

from ..base_ingestor import BaseIngestor
from ...rag import parse_document, chunk_text


class PdfIngestor(BaseIngestor):
    """Wraps the existing parse_document/chunk_text pair used by /api/upload
    today, normalized to the BaseIngestor contract."""

    def __init__(self):
        super().__init__("document")

    async def ingest(self, source: dict) -> list[dict]:
        parsed = await parse_document(source["filePath"], "application/pdf")
        chunks = chunk_text(parsed["text"])
        return [{"content": c, "metadata": {"page_number": None}} for c in chunks]

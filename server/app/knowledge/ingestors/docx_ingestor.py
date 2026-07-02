from ..base_ingestor import BaseIngestor


class DocxIngestor(BaseIngestor):
    def __init__(self):
        super().__init__("document")

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError("DocxIngestor not implemented — see rag.parse_document for the wired docx path")

from ..base_ingestor import BaseIngestor


class PptxIngestor(BaseIngestor):
    def __init__(self):
        super().__init__("document")

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError("PptxIngestor not implemented — slide-by-slide text + speaker notes extraction needed")

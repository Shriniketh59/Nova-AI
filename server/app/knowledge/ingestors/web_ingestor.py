from ..base_ingestor import BaseIngestor


class WebIngestor(BaseIngestor):
    def __init__(self):
        super().__init__("web")

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError("WebIngestor not implemented — needs fetch + readability-style main-content extraction")

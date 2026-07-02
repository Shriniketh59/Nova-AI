from ..base_ingestor import BaseIngestor


class YoutubeIngestor(BaseIngestor):
    def __init__(self):
        super().__init__("youtube")

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError("YoutubeIngestor not implemented — needs transcript fetch")

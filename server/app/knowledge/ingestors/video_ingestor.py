from ..base_ingestor import BaseIngestor


class VideoIngestor(BaseIngestor):
    def __init__(self):
        super().__init__("video")

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError("VideoIngestor not implemented — needs audio extraction (ffmpeg) + AudioIngestor")

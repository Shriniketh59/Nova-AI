from ..base_ingestor import BaseIngestor


class AudioIngestor(BaseIngestor):
    def __init__(self):
        super().__init__("audio")

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError("AudioIngestor not implemented — needs local whisper transcription")

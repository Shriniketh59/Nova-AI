from ..base_ingestor import BaseIngestor


class RepoIngestor(BaseIngestor):
    def __init__(self):
        super().__init__("code")

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError("RepoIngestor not implemented — needs clone + file-walk + per-file CodeIngestor dispatch")

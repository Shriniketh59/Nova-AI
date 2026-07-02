from ..base_ingestor import BaseIngestor


class CodeIngestor(BaseIngestor):
    def __init__(self):
        super().__init__("code")

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError("CodeIngestor not implemented — needs per-language AST chunking (e.g. tree-sitter)")

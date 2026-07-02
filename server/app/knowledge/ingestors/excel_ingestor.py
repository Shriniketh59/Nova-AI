from ..base_ingestor import BaseIngestor


class ExcelIngestor(BaseIngestor):
    def __init__(self):
        super().__init__("document")

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError("ExcelIngestor not implemented — add openpyxl and sheet-to-row chunking")

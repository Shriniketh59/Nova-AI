from ..base_ingestor import BaseIngestor


class CsvIngestor(BaseIngestor):
    """One chunk per row, header repeated for context so each chunk is
    independently meaningful to the embedding model."""

    def __init__(self):
        super().__init__("document")

    async def ingest(self, source: dict) -> list[dict]:
        with open(source["filePath"], "r", encoding="utf-8") as f:
            raw = f.read()
        lines = [l for l in raw.splitlines() if l.strip()]
        if not lines:
            return []

        header = lines[0]
        return [
            {"content": f"{header}\n{row}", "metadata": {"line_start": i + 2, "line_end": i + 2}}
            for i, row in enumerate(lines[1:])
        ]

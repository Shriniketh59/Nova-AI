class BaseIngestor:
    """Common contract every source-type ingestor implements. ingestor_registry.py
    picks the right one by mime-type/source-type and the rest of the pipeline
    (embedding, storage, retrieval) never needs to know which ingestor ran."""

    def __init__(self, source_type: str):
        if type(self) is BaseIngestor:
            raise TypeError("BaseIngestor is abstract and cannot be instantiated directly")
        self.source_type = source_type  # 'document' | 'code' | 'web' | 'youtube' | 'audio' | 'video'

    async def ingest(self, source: dict) -> list[dict]:
        raise NotImplementedError(f"{type(self).__name__}.ingest() not implemented")

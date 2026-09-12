import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_domain(url: str | None) -> str:
    if not url:
        return "local"
    try:
        parsed = urlparse(url)
        domain = parsed.hostname or url
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.lower()
    except Exception:
        return "unknown"


def calculate_freshness_score(published_or_updated_at: str | None, half_life_days: float = 180.0) -> float:
    """Calculates an exponential decay freshness score between 0.0 and 1.0.
    freshness = exp(-ln(2) * age_in_days / half_life_days)
    If timestamp is missing, returns a neutral score (0.5)."""
    if not published_or_updated_at:
        return 0.5
    try:
        # Handle ISO strings
        clean_ts = published_or_updated_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_ts)
        now = datetime.now(timezone.utc)
        age_seconds = max(0.0, (now - dt).total_seconds())
        age_days = age_seconds / 86400.0
        decay = math.log(2) / max(1.0, half_life_days)
        return round(math.exp(-decay * age_days), 4)
    except Exception:
        return 0.5


@dataclass
class DocumentMetadata:
    document_id: str
    source_url: str | None = None
    source_domain: str = "local"
    title: str = "Untitled Document"
    content_hash: str = ""
    document_version: int = 1
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    fetched_at: str = field(default_factory=utc_now_iso)
    published_at: str | None = None
    source_type: str = "file"  # file, web, code, api, manual
    language: str = "en"
    category: str = "general"
    freshness_score: float = 1.0
    authority_score: float = 0.5
    etag: str | None = None
    last_modified_header: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentChunk:
    chunk_id: str
    document_id: str
    content: str
    chunk_index: int
    content_hash: str
    page_number: int | None = None
    section_heading: str | None = None
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("embedding") is not None and not isinstance(d["embedding"], list):
            d["embedding"] = list(d["embedding"])
        return d


@dataclass
class Document:
    metadata: DocumentMetadata
    raw_content: str
    cleaned_content: str
    chunks: list[DocumentChunk] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "cleaned_content": self.cleaned_content,
            "chunks": [c.to_dict() for c in self.chunks],
        }

from .ingestors.pdf_ingestor import PdfIngestor
from .ingestors.text_ingestor import TextIngestor
from .ingestors.csv_ingestor import CsvIngestor
from .ingestors.excel_ingestor import ExcelIngestor
from .ingestors.docx_ingestor import DocxIngestor
from .ingestors.pptx_ingestor import PptxIngestor
from .ingestors.code_ingestor import CodeIngestor
from .ingestors.repo_ingestor import RepoIngestor
from .ingestors.web_ingestor import WebIngestor
from .ingestors.youtube_ingestor import YoutubeIngestor
from .ingestors.audio_ingestor import AudioIngestor
from .ingestors.video_ingestor import VideoIngestor

MIME_MAP = {
    "application/pdf": PdfIngestor,
    "text/plain": TextIngestor,
    "text/markdown": TextIngestor,
    "text/csv": CsvIngestor,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxIngestor,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": PptxIngestor,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ExcelIngestor,
    "application/vnd.ms-excel": ExcelIngestor,
}

CODE_EXTENSIONS = {".js", ".ts", ".jsx", ".tsx", ".py", ".java", ".cpp", ".c", ".h", ".hpp"}

SOURCE_TYPE_MAP = {
    "web": WebIngestor,
    "youtube": YoutubeIngestor,
    "audio": AudioIngestor,
    "video": VideoIngestor,
    "repo": RepoIngestor,
}


def resolve_ingestor(mime_type: str | None = None, extension: str | None = None, source_type: str | None = None):
    """Resolves the right ingestor for an uploaded file or external source."""
    if source_type and source_type in SOURCE_TYPE_MAP:
        return SOURCE_TYPE_MAP[source_type]()
    if extension and extension.lower() in CODE_EXTENSIONS:
        return CodeIngestor()
    if mime_type and mime_type in MIME_MAP:
        return MIME_MAP[mime_type]()
    raise ValueError(f"No ingestor registered for mimeType={mime_type} extension={extension} sourceType={source_type}")

import re
from urllib.parse import urlparse
import httpx

from ..base_ingestor import BaseIngestor
from ..cleaning import clean_content
from ..chunking import split_structured_text


def _strip_html(html: str) -> str:
    # Strip script and style blocks
    text = re.sub(r"<(script|style|nav|footer|header)[^>]*>[\s\S]*?</\1>", "", html, flags=re.I)
    # Replace block tags with newlines
    text = re.sub(r"<(?:p|div|h[1-6]|li|br|tr)[^>]*>", "\n", text, flags=re.I)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Unescape common HTML entities
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return text


class WebIngestor(BaseIngestor):
    """Fetches web page content, extracts main readable text, and splits into structured chunks."""

    def __init__(self):
        super().__init__("web")

    async def ingest(self, source: dict) -> list[dict]:
        url = source.get("url") or source.get("filePath")
        if not url:
            raise ValueError("WebIngestor requires 'url'")

        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            res = await client.get(url, headers={"User-Agent": "NovaAI-WebIngestor/1.0"})
            res.raise_for_status()
            html = res.text

        title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
        title = title_match.group(1).strip() if title_match else url

        raw_text = _strip_html(html)
        cleaned = clean_content(raw_text)

        chunks = split_structured_text(cleaned, target_size=750, document_id=url)

        return [
            {
                "content": c.content,
                "metadata": {
                    "source_url": url,
                    "title": title,
                    "section_heading": c.section_heading,
                    "source_type": "web",
                },
            }
            for c in chunks
        ]

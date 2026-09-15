import asyncio
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, List, Optional
from urllib.parse import urlparse
import httpx

from ..core.logger import logger
from ..jobs.cache import get_cached_fetch, set_cached_fetch

WEB_RETRIEVER_PROVIDER = os.environ.get("WEB_RETRIEVER_PROVIDER", "auto").lower()
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")
EXA_API_KEY = os.environ.get("EXA_API_KEY")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_domain(url: str) -> str:
    try:
        host = urlparse(url).hostname or url
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return "unknown"


@dataclass
class WebSearchResult:
    url: str
    title: str
    content: str
    source_domain: str
    published_at: Optional[str] = None
    updated_at: Optional[str] = None
    retrieval_timestamp: str = field(default_factory=_utc_now_iso)
    relevance_score: float = 0.5
    raw_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WebRetriever(ABC):
    """Abstract base class for all fresh web retrieval providers."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> List[WebSearchResult]:
        """Performs fresh web search for query and returns structured results."""
        pass


class TavilyWebRetriever(WebRetriever):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__("tavily")
        self.api_key = api_key or TAVILY_API_KEY

    async def search(self, query: str, max_results: int = 5) -> List[WebSearchResult]:
        if not self.api_key:
            logger.warn("web_retriever.tavily_missing_key", {"msg": "TAVILY_API_KEY not configured"})
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "search_depth": "basic",
                        "include_answer": False,
                        "max_results": max_results,
                    },
                )
                res.raise_for_status()
                data = res.json()
                results = []
                for r in data.get("results", []):
                    url = r.get("url", "")
                    results.append(
                        WebSearchResult(
                            url=url,
                            title=r.get("title", ""),
                            content=r.get("content", ""),
                            source_domain=_extract_domain(url),
                            published_at=r.get("published_date"),
                            relevance_score=float(r.get("score", 0.7)),
                        )
                    )
                return results
        except Exception as err:
            logger.error("web_retriever.tavily_failed", {"error": str(err)})
            return []


class FirecrawlWebRetriever(WebRetriever):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__("firecrawl")
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY") or FIRECRAWL_API_KEY

    async def search(self, query: str, max_results: int = 5) -> List[WebSearchResult]:
        print(f"[Firecrawl] web_retriever calling Firecrawl Search API for: '{query}' (has_key={bool(self.api_key)})")
        logger.info("web_retriever.firecrawl_search", {"query": query, "has_key": bool(self.api_key)})

        if self.api_key:
            try:
                async with httpx.AsyncClient(timeout=25) as client:
                    res = await client.post(
                        "https://api.firecrawl.dev/v1/search",
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json={"query": query, "limit": max_results},
                    )
                    res.raise_for_status()
                    data = res.json()
                    results = []
                    for r in data.get("data", []):
                        url = r.get("url", "") or r.get("metadata", {}).get("sourceURL", "")
                        content = r.get("markdown", "") or r.get("description", "") or r.get("metadata", {}).get("description", "")
                        if len(content) > 1200:
                            content = content[:1200] + "..."
                        results.append(
                            WebSearchResult(
                                url=url,
                                title=r.get("title", "") or r.get("metadata", {}).get("title", ""),
                                content=content,
                                source_domain=_extract_domain(url),
                                published_at=r.get("metadata", {}).get("publishedTime"),
                                relevance_score=0.85,
                            )
                        )
                    if results:
                        print(f"[Firecrawl] web_retriever retrieved {len(results)} fresh results from Firecrawl")
                        return results
            except Exception as err:
                logger.error("web_retriever.firecrawl_failed", {"error": str(err)})
                print(f"[Firecrawl] Search error: {err}. Using backup web search provider.")

        # Fallback to DDGS if key not configured or API call failed
        print(f"[Firecrawl] Running web search fallback for: '{query}'")
        ddgs = DDGSWebRetriever()
        return await ddgs.search(query, max_results=max_results)


class ExaWebRetriever(WebRetriever):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__("exa")
        self.api_key = api_key or EXA_API_KEY

    async def search(self, query: str, max_results: int = 5) -> List[WebSearchResult]:
        if not self.api_key:
            logger.warn("web_retriever.exa_missing_key", {"msg": "EXA_API_KEY not configured"})
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.post(
                    "https://api.exa.ai/search",
                    headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                    json={"query": query, "numResults": max_results, "useAutoprompt": True},
                )
                res.raise_for_status()
                data = res.json()
                results = []
                for r in data.get("results", []):
                    url = r.get("url", "")
                    results.append(
                        WebSearchResult(
                            url=url,
                            title=r.get("title", ""),
                            content=r.get("text", "") or r.get("snippet", ""),
                            source_domain=_extract_domain(url),
                            published_at=r.get("publishedDate"),
                            relevance_score=float(r.get("score", 0.7)),
                        )
                    )
                return results
        except Exception as err:
            logger.error("web_retriever.exa_failed", {"error": str(err)})
            return []


class DDGSWebRetriever(WebRetriever):
    """Default zero-configuration async web retriever using DuckDuckGo with
    exponential backoff retry, timeout protection, and in-memory TTL caching."""

    def __init__(self):
        super().__init__("ddgs")

    async def search(self, query: str, max_results: int = 5) -> List[WebSearchResult]:
        cache_key = f"ddgs::{query.strip().lower()}::{max_results}"
        cached = get_cached_fetch(cache_key)
        if cached is not None:
            return [WebSearchResult(**item) for item in cached]

        loop = asyncio.get_running_loop()

        def _blocking_search():
            try:
                from ddgs import DDGS
                with DDGS() as ddgs:
                    # Request slightly more candidates for deduplication
                    raw = list(ddgs.text(query, max_results=max_results + 2))
                    return raw
            except Exception as e:
                logger.warn("web_retriever.ddgs_fetch_error", {"query": query, "error": str(e)})
                return []

        # Execute in thread with bounded retries and exponential backoff
        raw_results = []
        for attempt in range(2):
            try:
                raw_results = await asyncio.wait_for(loop.run_in_executor(None, _blocking_search), timeout=8.0)
                if raw_results:
                    break
            except asyncio.TimeoutError:
                logger.warn("web_retriever.ddgs_timeout", {"query": query, "attempt": attempt + 1})
            except Exception as e:
                logger.warn("web_retriever.ddgs_attempt_error", {"error": str(e)})
            if attempt == 0:
                await asyncio.sleep(0.5)

        results: List[WebSearchResult] = []
        seen_urls = set()

        for r in raw_results:
            url = (r.get("href") or r.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                WebSearchResult(
                    url=url,
                    title=r.get("title", ""),
                    content=r.get("body", "") or r.get("snippet", ""),
                    source_domain=_extract_domain(url),
                    published_at=None,
                    relevance_score=0.65,
                )
            )
            if len(results) >= max_results:
                break

        # Cache valid results for 5 minutes
        if results:
            set_cached_fetch(cache_key, [r.to_dict() for r in results], ttl_ms=300000)

        return results


def get_web_retriever(provider: Optional[str] = None) -> WebRetriever:
    """Factory: resolves the appropriate web retriever. Default is DDGS (no API key needed)."""
    p = (provider or os.environ.get("WEB_RETRIEVER_PROVIDER") or "ddgs").lower()

    if p == "tavily" and TAVILY_API_KEY:
        return TavilyWebRetriever()
    if p == "exa" and EXA_API_KEY:
        return ExaWebRetriever()
    if p == "firecrawl" and FIRECRAWL_API_KEY:
        return FirecrawlWebRetriever()

    # Default: DDGS — zero configuration, no API key
    return DDGSWebRetriever()


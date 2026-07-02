import base64
import os

import httpx

from ..core.config import OLLAMA_URL
from .base_agent import BaseAgent

OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "llava")

SYSTEM_PROMPT = """You are Nova AI's Vision Agent. Analyze ONLY the attached image —
extract any visible text (OCR), describe charts/tables/screenshots/documents shown,
and answer the user's request grounded strictly in what is visible. Never search
external websites or substitute outside knowledge for what the image actually shows."""


class VisionAgent(BaseAgent):
    """Highest-priority route: an attached image always wins over document/RAG/web
    search. Uses Ollama's multimodal chat endpoint (image bytes as base64)."""

    def __init__(self):
        super().__init__("VisionAgent")

    async def run(self, query: str, context: dict | None = None) -> dict:
        context = context or {}
        file_path = context.get("filePath")
        file_name = context.get("fileName", "image")
        if not file_path or not os.path.exists(file_path):
            return {"success": False, "output": {"answer": f"Could not read image {file_name}."}, "error": "file_missing"}

        try:
            with open(file_path, "rb") as f:
                image_base64 = base64.b64encode(f.read()).decode("utf-8")

            async with httpx.AsyncClient(timeout=120) as client:
                res = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_VISION_MODEL,
                        "stream": False,
                        "options": {"temperature": 0.2, "num_predict": 1200},
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": query or "Describe and analyze this image.", "images": [image_base64]},
                        ],
                    },
                )
                if res.status_code >= 400:
                    raise RuntimeError(f"Vision LLM call failed: {res.status_code}")

                data = res.json()
                return {"success": True, "output": {"answer": (data.get("message") or {}).get("content", "")}}
        except Exception as err:
            return {"success": False, "output": {"answer": f"Vision analysis failed: {err}"}, "error": str(err)}

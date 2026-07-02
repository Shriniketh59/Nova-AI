import httpx

from ..core.config import OLLAMA_URL, OLLAMA_MODEL
from ..services.ats_service import calculate_ats_score
from .base_agent import BaseAgent

SYSTEM_PROMPT = """You are Nova AI's Resume Analysis Agent.
Analyze ONLY the resume text provided. Never reference external websites, resume builders, or ATS checker tools — you are the analysis, not a referral to one.
Structure your response with these exact headings: Skills Analysis, Project Analysis, Resume Improvements."""


class ResumeAnalysisAgent(BaseAgent):
    """"Review my resume" — combines real extraction (skills/sections, same
    parser ATS scoring uses) with a grounded LLM qualitative pass."""

    def __init__(self):
        super().__init__("ResumeAnalysisAgent")

    async def run(self, query: str, context: dict | None = None) -> dict:
        context = context or {}
        document_text = context.get("documentText", "")
        file_name = context.get("fileName", "resume")
        if not document_text.strip():
            return {"success": True, "output": {"answer": f"Could not extract any text from {file_name}."}}

        extraction = calculate_ats_score(document_text)

        try:
            skills_line = ", ".join(extraction["skillsFound"]) or "none detected"
            sections_line = ", ".join(k for k, v in extraction["sectionsDetected"].items() if v) or "none"
            async with httpx.AsyncClient(timeout=120) as client:
                res = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 1200},
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": (
                                    f"Resume ({file_name}):\n{document_text}\n\n"
                                    f"Extracted skills: {skills_line}\nSections detected: {sections_line}\n\nRequest: {query}"
                                ),
                            },
                        ],
                    },
                )
                if res.status_code >= 400:
                    raise RuntimeError(f"Resume analysis LLM call failed: {res.status_code}")

                data = res.json()
                answer = (data.get("message") or {}).get("content", "")
                return {"success": True, "output": {"answer": answer, "atsScore": extraction["score"], "skillsFound": extraction["skillsFound"]}}
        except Exception as err:
            return {"success": False, "output": {"answer": ""}, "error": str(err)}

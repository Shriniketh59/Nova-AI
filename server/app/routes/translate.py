from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents.translation_agent import TranslationAgent, SUPPORTED_LANGUAGES

router = APIRouter()
translation_agent = TranslationAgent()


class TranslateBody(BaseModel):
    text: str | None = None
    targetLanguage: str | None = None


@router.post("/api/translate")
async def translate(body: TranslateBody):
    if not body.text or not body.targetLanguage:
        raise HTTPException(status_code=400, detail={"error": "text and targetLanguage are required", "supportedLanguages": SUPPORTED_LANGUAGES})

    result = await translation_agent.run(body.text, {"targetLanguage": body.targetLanguage})
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return result["output"]

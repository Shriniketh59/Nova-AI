"""
Orchestrator route — SSE streaming endpoint for the Local Orchestrator.

POST /api/orchestrator/stream
  Body: {"query": str, "chatId"?: str, "history"?: [...]}
  Response: text/event-stream of SSE events

This is the new primary chat endpoint for Nova AI.
The existing /api/chats/{chat_id}/query route continues to work alongside this.
"""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.logger import logger
from ..orchestrator.local_orchestrator import orchestrate_stream

router = APIRouter()


class OrchestratorRequest(BaseModel):
    query: str
    chatId: str | None = None
    history: list[dict] | None = None


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@router.post("/api/orchestrator/stream")
async def orchestrator_stream(body: OrchestratorRequest):
    if not body.query or not body.query.strip():
        raise HTTPException(status_code=400, detail="query is required")

    async def stream():
        try:
            async for event in orchestrate_stream(
                query=body.query.strip(),
                chat_id=body.chatId or "",
                conversation_history=body.history,
                is_voice=False,
            ):
                yield _sse(event)
        except Exception as e:
            logger.error("orchestrator_route.stream_error", {"error": str(e)})
            yield _sse({"error": str(e)})
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")

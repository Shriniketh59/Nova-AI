import asyncio
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agents.code_agent import CodeAgent
from ..agents.memory_agent import memory_agent
from ..agents.tool_agent import ToolAgent
from ..core import db
from ..core.logger import logger
from ..middleware.auth_middleware import get_current_user
from ..rag import fetch_chunks_for_chat, fetch_images_for_chat
from ..services.document_type_detector import detect_document_request, build_summary
from ..services.task_router import classify_task
from ..utils.stream_cancel import drain_task_queue

router = APIRouter()

tool_agent = ToolAgent()
code_agent = CodeAgent()

STAGE_LABELS = {
    "planning": "Analyzing your question...",
    "memory": "Checking earlier context...",
    "researching": "Gathering evidence from sources...",
    "reasoning": "Reasoning through the evidence...",
    "reviewing": "Reviewing the answer for accuracy...",
    "regenerating": "Found an issue — revising the answer...",
}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


class AgentChatBody(BaseModel):
    chatId: str | None = None
    message: str | None = None


@router.post("/api/agent/chat")
async def agent_chat(body: AgentChatBody, current_user: dict = Depends(get_current_user)):
    if not body.chatId or not body.message:
        raise HTTPException(status_code=400, detail="chatId and message are required")

    chat_id = body.chatId
    message = body.message
    user_id = current_user["id"]

    chat_check = await db.query("SELECT id FROM chats WHERE id = $1 AND user_id = $2", [chat_id, user_id])
    if chat_check["rowCount"] == 0:
        raise HTTPException(status_code=404, detail="Chat not found")

    async def stream():
        req_id = f"{chat_id}-{int(time.time() * 1000)}"
        try:
            user_msg_result = await db.query(
                "INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *",
                [chat_id, "user", message],
            )
            user_msg = user_msg_result["rows"][0]
            try:
                await memory_agent.extract_memory(user_id, chat_id, message)
            except Exception:
                pass

            all_chat_chunks = await fetch_chunks_for_chat(chat_id)
            chat_images = await fetch_images_for_chat(chat_id)
            has_files = len(all_chat_chunks) > 0
            has_images = len(chat_images) > 0
            file_count = len({c["file_id"] for c in all_chat_chunks})
            task = classify_task(message, has_files=has_files, has_images=has_images, file_count=file_count)
            logger.info("task.route", {"reqId": req_id, "type": task["type"], "hasFiles": has_files, "hasImages": has_images})

            if task["type"] == "coding":
                try:
                    token_queue: asyncio.Queue = asyncio.Queue()
                    code_answer_parts = []

                    def on_token(token):
                        code_answer_parts.append(token)
                        token_queue.put_nowait("".join(code_answer_parts))

                    gen_task = asyncio.create_task(code_agent.run_stream(message, on_token))

                    # Cancels gen_task if the client aborts mid-stream.
                    async for text in drain_task_queue(gen_task, token_queue):
                        yield _sse({"text": text, "sources": []})

                    result = await gen_task
                    code_answer = result["answer"]
                    confidence = result["confidence"]
                    await db.query("INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)", [chat_id, "ai", code_answer])
                    await db.query("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1", [chat_id])
                    yield _sse({"text": code_answer, "sources": [], "confidence": confidence})
                except Exception as err:
                    yield _sse({"error": str(err)})
                yield "data: [DONE]\n\n"
                return

            stage_queue: asyncio.Queue = asyncio.Queue()

            def on_stage(stage):
                stage_queue.put_nowait({"stage": stage, "stageLabel": STAGE_LABELS.get(stage, stage)})

            tool_agent_task = asyncio.create_task(
                tool_agent.run(message, {"chatId": chat_id, "excludeMessageId": user_msg["id"], "onStage": on_stage, "hasFiles": has_files})
            )

            # Cancels the whole multi-agent run if the client aborts.
            async for event in drain_task_queue(tool_agent_task, stage_queue, poll_interval=0.2):
                yield _sse(event)

            result = await tool_agent_task

            if not result["success"]:
                raise RuntimeError(result.get("error") or "Agent execution failed")

            output = result["output"]
            answer, evidence, confidence, contradictions = output["answer"], output["evidence"], output["confidence"], output["contradictions"]

            doc_type = detect_document_request(message)
            document = None
            if doc_type:
                document = {
                    "title": doc_type["label"],
                    "subtitle": None,
                    "type": doc_type["type"],
                    "summary": build_summary(answer),
                    "content": answer,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "exportFormats": ["docx", "pdf", "pptx", "xlsx", "markdown", "txt"],
                }

            await db.query(
                "INSERT INTO messages (chat_id, role, content, document) VALUES ($1, $2, $3, $4)",
                [chat_id, "ai", answer, json.dumps(document) if document else None],
            )
            await db.query("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1", [chat_id])

            yield _sse({"text": answer, "sources": evidence, "confidence": confidence, "contradictions": contradictions, "document": document})
            yield "data: [DONE]\n\n"
        except Exception as err:
            logger.error("agentChat.failed", {"chatId": chat_id, "error": str(err)})
            yield _sse({"error": str(err)})
            yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")

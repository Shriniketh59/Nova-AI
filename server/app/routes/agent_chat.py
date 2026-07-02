import asyncio
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agents.code_agent import CodeAgent
from ..agents.document_analysis_agent import DocumentAnalysisAgent
from ..agents.document_comparison_agent import DocumentComparisonAgent
from ..agents.memory_agent import memory_agent
from ..agents.resume_analysis_agent import ResumeAnalysisAgent
from ..agents.supervisor_agent import SupervisorAgent
from ..agents.vision_agent import VisionAgent
from ..core import db
from ..core.config import DEFAULT_USER_ID
from ..core.logger import logger
from ..rag import fetch_chunks_for_chat, fetch_images_for_chat
from ..services.ats_service import calculate_ats_score, format_ats_answer
from ..services.document_type_detector import detect_document_request, build_summary
from ..services.task_router import classify_task

router = APIRouter()

supervisor = SupervisorAgent()
document_analysis_agent = DocumentAnalysisAgent()
document_comparison_agent = DocumentComparisonAgent()
resume_analysis_agent = ResumeAnalysisAgent()
vision_agent = VisionAgent()
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
async def agent_chat(body: AgentChatBody):
    if not body.chatId or not body.message:
        raise HTTPException(status_code=400, detail="chatId and message are required")

    chat_id = body.chatId
    message = body.message

    async def stream():
        req_id = f"{chat_id}-{int(time.time() * 1000)}"
        try:
            user_msg_result = await db.query(
                "INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *",
                [chat_id, "user", message],
            )
            user_msg = user_msg_result["rows"][0]
            try:
                await memory_agent.extract_memory(DEFAULT_USER_ID, chat_id, message)
            except Exception:
                pass

            all_chat_chunks = await fetch_chunks_for_chat(chat_id)
            chat_images = await fetch_images_for_chat(chat_id)
            has_files = len(all_chat_chunks) > 0
            has_images = len(chat_images) > 0
            file_count = len({c["file_id"] for c in all_chat_chunks})
            task = classify_task(message, has_files=has_files, has_images=has_images, file_count=file_count)
            logger.info("task.route", {"reqId": req_id, "type": task["type"], "hasFiles": has_files, "hasImages": has_images})

            if task["type"] == "vision":
                image = chat_images[-1]
                result = await vision_agent.run(message, {"filePath": image["file_path"], "fileName": image["original_filename"]})
                answer = result["output"]["answer"]
                confidence = {"score": 75 if result["success"] else 0, "label": "high" if result["success"] else "low", "reason": "Based on uploaded image content only."}

                await db.query("INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)", [chat_id, "ai", answer])
                await db.query("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1", [chat_id])
                yield _sse({"text": answer, "sources": [{"filename": image["original_filename"], "type": "image"}], "confidence": confidence})
                yield "data: [DONE]\n\n"
                return

            if task["type"] == "coding":
                try:
                    token_queue: asyncio.Queue = asyncio.Queue()
                    code_answer_parts = []

                    def on_token(token):
                        code_answer_parts.append(token)
                        token_queue.put_nowait("".join(code_answer_parts))

                    gen_task = asyncio.create_task(code_agent.run_stream(message, on_token))

                    while not gen_task.done():
                        try:
                            text = await asyncio.wait_for(token_queue.get(), timeout=0.1)
                            yield _sse({"text": text, "sources": []})
                        except asyncio.TimeoutError:
                            continue
                    while not token_queue.empty():
                        yield _sse({"text": token_queue.get_nowait(), "sources": []})

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

            if task["type"] != "general":
                document_text = "\n".join(c["content"] for c in all_chat_chunks)
                file_name = all_chat_chunks[0]["original_filename"] if all_chat_chunks else "document"

                if task["type"] == "document_comparison":
                    by_file: dict = {}
                    for chunk in all_chat_chunks:
                        existing = by_file.setdefault(chunk["file_id"], {"fileName": chunk["original_filename"], "text": ""})
                        existing["text"] += f"{chunk['content']}\n"
                    documents = list(by_file.values())
                    result = await document_comparison_agent.run(message, {"documents": documents})
                    answer = result["output"]["answer"]
                    confidence = {"score": 75 if result["success"] else 0, "label": "high" if result["success"] else "low", "reason": "Based on the uploaded documents only."}
                    source_cards = [{"filename": d["fileName"], "type": "document"} for d in documents]

                    await db.query("INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)", [chat_id, "ai", answer])
                    await db.query("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1", [chat_id])
                    yield _sse({"text": answer, "sources": source_cards, "confidence": confidence})
                    yield "data: [DONE]\n\n"
                    return

                if task["type"] == "ats":
                    ats_result = calculate_ats_score(document_text)
                    answer = format_ats_answer(ats_result)
                    confidence = {"score": ats_result["score"], "label": "high" if ats_result["score"] >= 70 else "medium" if ats_result["score"] >= 30 else "low", "reason": "Calculated from parsed resume content."}
                elif task["type"] == "resume_analysis":
                    result = await resume_analysis_agent.run(message, {"documentText": document_text, "fileName": file_name})
                    answer = result["output"]["answer"]
                    confidence = {"score": 75 if result["success"] else 0, "label": "high" if result["success"] else "low", "reason": "Based on uploaded resume content only."}
                else:
                    result = await document_analysis_agent.run(message, {"documentText": document_text, "fileName": file_name})
                    answer = result["output"]["answer"]
                    confidence = {"score": 75 if result["success"] else 0, "label": "high" if result["success"] else "low", "reason": "Based on uploaded document content only."}

                await db.query("INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)", [chat_id, "ai", answer])
                await db.query("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1", [chat_id])
                yield _sse({"text": answer, "sources": [{"filename": file_name, "type": "document"}], "confidence": confidence})
                yield "data: [DONE]\n\n"
                return

            stage_queue: asyncio.Queue = asyncio.Queue()

            def on_stage(stage):
                stage_queue.put_nowait({"stage": stage, "stageLabel": STAGE_LABELS.get(stage, stage)})

            supervisor_task = asyncio.create_task(
                supervisor.run(message, {"chatId": chat_id, "excludeMessageId": user_msg["id"], "onStage": on_stage, "hasFiles": has_files})
            )

            while not supervisor_task.done():
                try:
                    event = await asyncio.wait_for(stage_queue.get(), timeout=0.2)
                    yield _sse(event)
                except asyncio.TimeoutError:
                    continue
            while not stage_queue.empty():
                yield _sse(stage_queue.get_nowait())

            result = await supervisor_task

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

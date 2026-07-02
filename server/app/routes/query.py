import asyncio
import json
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agents.code_agent import CodeAgent
from ..agents.document_analysis_agent import DocumentAnalysisAgent
from ..agents.document_comparison_agent import DocumentComparisonAgent
from ..agents.memory_agent import memory_agent
from ..agents.resume_analysis_agent import ResumeAnalysisAgent
from ..agents.vision_agent import VisionAgent
from ..core import db
from ..core.config import DEFAULT_USER_ID, RAG_API_URL
from ..core.logger import logger
from ..rag import fetch_chunks_for_chat, fetch_images_for_chat
from ..retrieval.complexity import tier_for
from ..retrieval.confidence_engine import compute_answer_confidence
from ..retrieval.retrieval_service import retrieve
from ..services.ats_service import calculate_ats_score, format_ats_answer
from ..services.document_type_detector import detect_document_request, build_summary
from ..services.rag_service import run_rag_query
from ..services.task_router import classify_task, classify_topic
from ..utils.context_manager import get_conversation_context

router = APIRouter()

document_analysis_agent = DocumentAnalysisAgent()
document_comparison_agent = DocumentComparisonAgent()
resume_analysis_agent = ResumeAnalysisAgent()
vision_agent = VisionAgent()
code_agent = CodeAgent()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


class ChatQueryBody(BaseModel):
    query: str | None = None
    fileId: str | None = None


@router.post("/api/chats/{chat_id}/query")
async def chat_query(chat_id: str, body: ChatQueryBody):
    query = body.query
    if not query:
        raise HTTPException(status_code=400, detail="Query text is required")

    async def stream():
        req_id = f"{chat_id}-{int(time.time() * 1000)}"
        try:
            user_msg_result = await db.query(
                "INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *",
                [chat_id, "user", query],
            )
            user_msg = user_msg_result["rows"][0]
            try:
                await memory_agent.extract_memory(DEFAULT_USER_ID, chat_id, query)
            except Exception:
                pass

            if body.fileId:
                await db.query(
                    "UPDATE uploaded_files SET message_id = $1 WHERE id = $2 AND user_id = $3",
                    [user_msg["id"], body.fileId, DEFAULT_USER_ID],
                )

            all_chat_chunks = await fetch_chunks_for_chat(chat_id)
            chat_images = await fetch_images_for_chat(chat_id)
            has_files = len(all_chat_chunks) > 0
            has_images = len(chat_images) > 0
            file_count = len({c["file_id"] for c in all_chat_chunks})
            task = classify_task(query, has_files=has_files, has_images=has_images, file_count=file_count)
            logger.info("task.route", {"reqId": req_id, "type": task["type"], "hasFiles": has_files, "hasImages": has_images})

            if task["type"] == "vision":
                image = chat_images[-1]
                result = await vision_agent.run(query, {"filePath": image["file_path"], "fileName": image["original_filename"]})
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

                    gen_task = asyncio.create_task(code_agent.run_stream(query, on_token))

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
                    logger.error("codeAgent.failed", {"chatId": chat_id, "error": str(err)})
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
                    result = await document_comparison_agent.run(query, {"documents": documents})
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
                    result = await resume_analysis_agent.run(query, {"documentText": document_text, "fileName": file_name})
                    answer = result["output"]["answer"]
                    confidence = {"score": 75 if result["success"] else 0, "label": "high" if result["success"] else "low", "reason": "Based on uploaded resume content only."}
                else:
                    result = await document_analysis_agent.run(query, {"documentText": document_text, "fileName": file_name})
                    answer = result["output"]["answer"]
                    confidence = {"score": 75 if result["success"] else 0, "label": "high" if result["success"] else "low", "reason": "Based on uploaded document content only."}

                await db.query("INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)", [chat_id, "ai", answer])
                await db.query("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1", [chat_id])
                yield _sse({"text": answer, "sources": [{"filename": file_name, "type": "document"}], "confidence": confidence})
                yield "data: [DONE]\n\n"
                return

            tier = tier_for(query)
            retrieval_result = await retrieve(query, chat_id, top_k=tier["topK"])
            memories = await memory_agent.get_relevant_memories(chat_id, query, user_msg["id"], 3)
            conversation_context = await get_conversation_context(chat_id)

            context_blocks = []
            if retrieval_result["contextText"]:
                context_blocks.append(f"[Document context]\n{retrieval_result['contextText']}")
            if memories:
                context_blocks.append(f"[Relevant earlier facts]\n{chr(10).join(memories)}")
            if conversation_context:
                context_blocks.append(conversation_context)
            context_text = "\n\n".join(context_blocks)

            use_web_search = not has_files and (
                retrieval_result["confidence"]["label"] != "high" or len(retrieval_result["chunks"]) < tier["minSources"]
            )

            accumulated_text = ""
            sources = []
            async with httpx.AsyncClient(timeout=180) as client:
                async with client.stream(
                    "POST",
                    f"{RAG_API_URL}/query/stream",
                    json={"query": query, "context": context_text, "web_search": use_web_search},
                ) as rag_res:
                    if rag_res.status_code >= 400:
                        raise RuntimeError(f"RAG API error: {rag_res.status_code}")

                    async for line in rag_res.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except Exception:
                            continue
                        if data.get("sources"):
                            sources = data["sources"]
                            yield _sse({"text": "", "sources": sources})
                        if data.get("token"):
                            accumulated_text += data["token"]
                            yield _sse({"text": accumulated_text, "sources": sources})
                        if data.get("replace") is not None:
                            # rag_api caught its own answer contradicting a
                            # knowledge-cutoff statement mid-stream and sent a
                            # corrected full answer to replace it with.
                            accumulated_text = data["replace"]
                            yield _sse({"text": accumulated_text, "sources": sources})

            web_source_cards = [{**s, "type": "web"} for s in sources]
            all_source_cards = [*retrieval_result["sources"], *web_source_cards]
            answer_confidence = compute_answer_confidence(
                source_count=len(all_source_cards),
                contradictions=[],
                doc_confidence=retrieval_result["confidence"],
                has_web_sources=len(web_source_cards) > 0,
                category=classify_topic(query),
            )

            doc_type = detect_document_request(query)
            document = None
            if doc_type:
                document = {
                    "title": doc_type["label"],
                    "subtitle": None,
                    "type": doc_type["type"],
                    "summary": build_summary(accumulated_text),
                    "content": accumulated_text,
                    "createdAt": datetime.now(timezone.utc).isoformat(),
                    "exportFormats": ["docx", "pdf", "pptx", "xlsx", "markdown", "txt"],
                }

            yield _sse({"text": accumulated_text, "sources": all_source_cards, "confidence": answer_confidence, "document": document})

            await db.query(
                "INSERT INTO messages (chat_id, role, content, document) VALUES ($1, $2, $3, $4)",
                [chat_id, "ai", accumulated_text, json.dumps(document) if document else None],
            )
            await db.query("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1", [chat_id])

            yield "data: [DONE]\n\n"
        except Exception as err:
            logger.error("chat.query.failed", {"chatId": chat_id, "error": str(err)})
            yield _sse({"error": str(err)})
            yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


class ChatRagBody(BaseModel):
    chatId: str | None = None
    message: str | None = None


@router.post("/api/chat/rag")
async def chat_rag(body: ChatRagBody):
    if not body.chatId or not body.message:
        raise HTTPException(status_code=400, detail="chatId and message are required")

    try:
        await db.query("INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)", [body.chatId, "user", body.message])

        result = await run_rag_query(body.message, body.chatId)

        await db.query("INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)", [body.chatId, "ai", result["answer"]])
        await db.query("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1", [body.chatId])

        return {"answer": result["answer"], "sources": result["sources"]}
    except Exception as err:
        logger.error("rag.chat.failed", {"chatId": body.chatId, "error": str(err)})
        raise HTTPException(status_code=500, detail="Failed to generate RAG response")

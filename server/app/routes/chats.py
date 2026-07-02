from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import db
from ..core.config import DEFAULT_USER_ID

router = APIRouter()


class CreateChatBody(BaseModel):
    title: str | None = None


class RenameChatBody(BaseModel):
    title: str


class CreateMessageBody(BaseModel):
    role: str
    content: str
    fileId: str | None = None


@router.get("/api/chats")
async def list_chats():
    result = await db.query("SELECT * FROM chats WHERE user_id = $1 ORDER BY updated_at DESC", [DEFAULT_USER_ID])
    return result["rows"]


@router.post("/api/chats", status_code=201)
async def create_chat(body: CreateChatBody):
    result = await db.query(
        "INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *",
        [DEFAULT_USER_ID, body.title or "New Chat"],
    )
    return result["rows"][0]


@router.put("/api/chats/{chat_id}")
async def rename_chat(chat_id: str, body: RenameChatBody):
    result = await db.query(
        "UPDATE chats SET title = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2 AND user_id = $3 RETURNING *",
        [body.title, chat_id, DEFAULT_USER_ID],
    )
    if result["rowCount"] == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    return result["rows"][0]


@router.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str):
    result = await db.query(
        "DELETE FROM chats WHERE id = $1 AND user_id = $2 RETURNING *",
        [chat_id, DEFAULT_USER_ID],
    )
    if result["rowCount"] == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"message": "Chat deleted successfully"}


@router.get("/api/chats/{chat_id}/messages")
async def get_messages(chat_id: str):
    chat_check = await db.query("SELECT id FROM chats WHERE id = $1 AND user_id = $2", [chat_id, DEFAULT_USER_ID])
    if chat_check["rowCount"] == 0:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = await db.query("SELECT * FROM messages WHERE chat_id = $1 ORDER BY created_at ASC", [chat_id])

    message_ids = [m["id"] for m in messages["rows"]]
    files = []
    if message_ids:
        files_result = await db.query(
            "SELECT id, message_id, filename, original_filename, mime_type, size_bytes FROM uploaded_files WHERE message_id = ANY($1::uuid[])",
            [message_ids],
        )
        files = files_result["rows"]

    enriched = []
    for m in messages["rows"]:
        file = next((f for f in files if f["message_id"] == m["id"]), None)
        enriched.append({
            **m,
            "attachment": (
                {"id": file["id"], "name": file["original_filename"], "type": file["mime_type"], "size": file["size_bytes"]}
                if file else None
            ),
        })
    return enriched


@router.post("/api/chats/{chat_id}/messages", status_code=201)
async def save_message(chat_id: str, body: CreateMessageBody):
    if not body.role or not body.content:
        raise HTTPException(status_code=400, detail="Role and content are required")

    chat_check = await db.query("SELECT id FROM chats WHERE id = $1 AND user_id = $2", [chat_id, DEFAULT_USER_ID])
    if chat_check["rowCount"] == 0:
        raise HTTPException(status_code=404, detail="Chat not found")

    result = await db.query(
        "INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *",
        [chat_id, body.role, body.content],
    )
    message = result["rows"][0]

    if body.fileId:
        await db.query(
            "UPDATE uploaded_files SET message_id = $1 WHERE id = $2 AND user_id = $3",
            [message["id"], body.fileId, DEFAULT_USER_ID],
        )

    await db.query("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1", [chat_id])

    return message


@router.get("/api/chats/{chat_id}/files")
async def get_chat_files(chat_id: str):
    files = await db.query(
        """SELECT id, original_filename as name, mime_type as type, size_bytes as size, created_at
           FROM uploaded_files
           WHERE message_id IN (SELECT id FROM messages WHERE chat_id = $1)
           ORDER BY created_at DESC""",
        [chat_id],
    )
    return files["rows"]

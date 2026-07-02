import os

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
IGNORE = {"node_modules", ".git", "dist", "uploads", "qdrant"}


def _resolve_safe(rel_path: str | None) -> str:
    """Resolves a user-supplied relative path against PROJECT_ROOT and rejects
    anything that escapes it — the only thing standing between "edit this
    project's files" and "read any file on the machine"."""
    target = os.path.abspath(os.path.join(PROJECT_ROOT, "." + os.sep + (rel_path or "")))
    if not target.startswith(PROJECT_ROOT):
        raise ValueError("Path escapes project root")
    return target


def _build_tree(dir_abs: str, rel_path: str = "") -> list[dict]:
    entries = [e for e in os.scandir(dir_abs) if e.name not in IGNORE and not e.name.startswith(".")]

    result = []
    for e in entries:
        entry_rel = f"{rel_path}/{e.name}" if rel_path else e.name
        if e.is_dir():
            result.append({"name": e.name, "path": entry_rel, "type": "dir", "children": _build_tree(os.path.join(dir_abs, e.name), entry_rel)})
        else:
            result.append({"name": e.name, "path": entry_rel, "type": "file"})

    result.sort(key=lambda x: (x["type"] != "dir", x["name"]))
    return result


@router.get("/api/fs/tree")
async def get_tree():
    try:
        tree = _build_tree(PROJECT_ROOT)
        return {"name": os.path.basename(PROJECT_ROOT), "path": "", "type": "dir", "children": tree}
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/api/fs/file")
async def get_file(path: str = Query(...)):
    try:
        target = _resolve_safe(path)
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
        return {"path": path, "content": content}
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))


class WriteFileBody(BaseModel):
    path: str
    content: str | None = None


@router.put("/api/fs/file")
async def write_file(body: WriteFileBody):
    try:
        target = _resolve_safe(body.path)
        with open(target, "w", encoding="utf-8") as f:
            f.write(body.content or "")
        return {"ok": True}
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))

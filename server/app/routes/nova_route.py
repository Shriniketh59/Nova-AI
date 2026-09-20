import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents.code_agent import CodeAgent
from ..agents.planner_agent import PlannerAgent
from ..agents.validation_agent import ValidationAgent

router = APIRouter()
code_agent = CodeAgent()
validation_agent = ValidationAgent()
planner_agent = PlannerAgent()

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
GENERATED_ROOT = os.path.join(PROJECT_ROOT, "generated")

_FILE_MARKER_RE = re.compile(r"//\s*FILE:\s*(\S+)|#\s*FILE:\s*(\S+)")


def _extract_files(markdown: str) -> list[dict]:
    lines = markdown.split("\n")
    files = []
    pending_path = None
    current_path = None
    in_fence = False
    fence_lines: list[str] = []

    for line in lines:
        if line.strip().startswith("```"):
            if not in_fence:
                in_fence = True
                fence_lines = []
                current_path = pending_path
                pending_path = None
            else:
                in_fence = False
                if current_path:
                    files.append({"path": current_path, "content": "\n".join(fence_lines).strip()})
                    current_path = None
            continue

        marker = _FILE_MARKER_RE.search(line)
        if marker:
            if in_fence and not current_path and all(not l.strip() for l in fence_lines):
                current_path = marker.group(1) or marker.group(2)
            elif not in_fence:
                pending_path = marker.group(1) or marker.group(2)
            continue

        if in_fence:
            fence_lines.append(line)

    return files


def _format_in_memory_file(rel_path: str, content: str) -> dict:
    safe_rel = re.sub(r"\.\.", "", rel_path.lstrip("/\\")).replace("\\", "/")
    return {"path": safe_rel, "content": content}


class NovaTaskBody(BaseModel):
    prompt: str | None = None


@router.post("/api/nova/task")
async def nova_task(body: NovaTaskBody):
    if not body.prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    try:
        plan_result = await planner_agent.run(body.prompt)
        plan = plan_result["output"]

        code_prompt = (
            f"{body.prompt}\n\nIf this requires multiple files, precede EVERY fenced code block with a marker line exactly like:\n"
            "// FILE: relative/path/to/file.ext\n(use # FILE: for Python/shell). Always include this marker, even for a single file."
        )
        code_result = await code_agent.run(code_prompt)
        answer = code_result["output"]["answer"]

        extracted = _extract_files(answer)
        # Keep generated files in-memory only — never write generated answers/code to project files
        generated_files = [_format_in_memory_file(f["path"], f["content"]) for f in extracted]

        critique = await validation_agent.critique(answer, question=body.prompt, evidence_summary=body.prompt, contradictions=[])

        return {
            "task": body.prompt,
            "plan": {"intent": plan["intent"], "steps": plan["steps"]},
            "files": generated_files,
            "summary": answer,
            "changes": [f"Generated in-memory: {f['path']}" for f in generated_files],
            "review": {"pass": critique["pass"], "issues": critique["issues"], "confidence": critique["confidenceScore"]},
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))

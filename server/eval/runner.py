"""Executes the eval dataset against a given pipeline configuration and
records raw per-item results (answer, latency, evidence, status) to
eval/runs/<timestamp>/raw_<config>.jsonl. Produces no metrics itself —
metrics.py, classification_eval.py, and report.py consume this raw output.

Task completion status definitions (assigned per item below):
  success             — pipeline returned an answer, no exception, no
                         timeout, and (where a hard gate ran) validation
                         did not reject it.
  failed              — an unhandled exception was raised by the pipeline.
  timeout             — the pipeline did not return within the per-item
                         bound (90s baseline/rag configs, 150s full/
                         validator configs — the full corrective loop can
                         run multiple LLM calls).
  validation_rejected — ValidationAgent.critique() (or ToolAgent's
                         verification-failure path) rejected the answer and
                         no corrected answer was produced.
  retrieval_failure   — the exception originated in retrieval (embedding
                         call, vector store, or web search), detected
                         heuristically from the exception message — this is
                         a coarse signal, not a guaranteed classification.
  tool_failure        — the exception originated in a non-retrieval agent
                         stage (planner/research/reasoning), same caveat.
  partial             — NOT auto-assigned. Multi-part/rubric items need a
                         human or rubric pass to detect partial coverage;
                         this runner reports "success"/"failed" only and
                         partial-completion analysis is left to report.py's
                         rubric grading step, which is explicitly marked
                         where it hasn't run.

This module requires a reachable local Ollama (OLLAMA_URL) and Postgres
(DATABASE_URL) — same requirements as `pytest server/tests`. It does not
mock either; every recorded value comes from a real call.
"""

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core import db as db_module
from app.core.config import DEFAULT_USER_ID, OLLAMA_URL, OLLAMA_MODEL, get_ollama_options

DATASET_DIR = Path(__file__).parent / "dataset"
RUNS_DIR = Path(__file__).parent / "runs"

CONFIGS = ["baseline_llm", "rag", "rag_memory", "rag_memory_tools", "rag_memory_tools_validator", "full"]

_SIMPLE_TIMEOUT_S = 90
_FULL_TIMEOUT_S = 150


def load_dataset(split: str) -> list[dict]:
    path = DATASET_DIR / f"{split}.jsonl"
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


async def _seed_fixture(item: dict) -> str | None:
    """Inserts fixture chunk(s) declared on a dataset item into a fresh chat
    so doc_query items have real, known-content evidence to retrieve against
    — mirrors tests/test_retrieval.py's _insert_chunk helper."""
    contents = []
    if item.get("fixture_content"):
        contents.append((item.get("fixture_filename") or "fixture.txt", item["fixture_content"]))
    if item.get("fixture_conflict"):
        contents.extend((c["filename"], c["content"]) for c in item["fixture_conflict"])
    if not contents:
        return None

    chat = await db_module.query("INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *", [DEFAULT_USER_ID, f"eval-{item['id']}"])
    chat_id = chat["rows"][0]["id"]
    for filename, content in contents:
        msg = await db_module.query("INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *", [chat_id, "user", "upload"])
        file = await db_module.query(
            "INSERT INTO uploaded_files (message_id, user_id, filename, original_filename, mime_type, size_bytes, file_path) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *",
            [msg["rows"][0]["id"], DEFAULT_USER_ID, filename, filename, "text/plain", len(content), f"/tmp/eval-{filename}"],
        )
        from app.rag import generate_embedding
        embedding = await generate_embedding(content)
        await db_module.query(
            "INSERT INTO document_chunks (file_id, content, embedding, page_number) VALUES ($1, $2, $3, $4)",
            [file["rows"][0]["id"], content, json.dumps(embedding), None],
        )
    return chat_id


async def _bare_llm(prompt: str, timeout: float = _SIMPLE_TIMEOUT_S) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": OLLAMA_MODEL, "stream": False, "options": get_ollama_options(), "messages": [{"role": "user", "content": prompt}]},
        )
        res.raise_for_status()
        data = res.json()
        return (data.get("message") or {}).get("content", "")


def _classify_exception(err: Exception) -> str:
    msg = str(err).lower()
    if any(k in msg for k in ("embedding", "retrieve", "vector", "chroma", "hybrid_search")):
        return "retrieval_failure"
    return "tool_failure"


def _classify_exception_detail(err: Exception) -> str:
    """Finer-grained label for error_analysis.py, independent of the
    coarse status bucket above (which only distinguishes retrieval vs
    everything-else for task-completion accounting)."""
    msg = str(err).lower()
    if any(k in msg for k in ("embedding", "retrieve", "vector", "chroma", "hybrid_search")):
        return "retrieval_miss"
    if any(k in msg for k in ("ollama", "connect", "model")):
        return "generation_error"
    if "memory" in msg:
        return "memory_error"
    if any(k in msg for k in ("budget", "token limit", "daily limit")):
        return "budget_exhaustion"
    return "tool_failure"


async def run_item(item: dict, config: str, user_id: str = DEFAULT_USER_ID) -> dict:
    t0 = time.perf_counter()
    status = "success"
    answer = ""
    evidence: list = []
    claims: list = []
    contradictions: list = []
    error_detail = None

    try:
        chat_id = await _seed_fixture(item)
        has_files = chat_id is not None
        query = item["query"]

        if config == "baseline_llm":
            answer = await asyncio.wait_for(_bare_llm(query), timeout=_SIMPLE_TIMEOUT_S)

        elif config == "rag":
            from app.retrieval.retrieval_service import retrieve
            result = await asyncio.wait_for(retrieve(query, chat_id or "", top_k=5), timeout=_SIMPLE_TIMEOUT_S)
            prompt = f"Evidence:\n{result['contextText']}\n\nQuestion: {query}" if result["contextText"] else query
            answer = await asyncio.wait_for(_bare_llm(prompt), timeout=_SIMPLE_TIMEOUT_S)
            evidence = result["sources"]

        elif config == "rag_memory":
            from app.retrieval.retrieval_service import retrieve
            from app.agents.memory_agent import memory_agent
            result = await asyncio.wait_for(retrieve(query, chat_id or "", top_k=5), timeout=_SIMPLE_TIMEOUT_S)
            try:
                memories = await memory_agent.get_relevant_memories(chat_id or "", query, top_k=3, user_id=user_id)
            except Exception:
                memories = []
            mem_block = ("\n".join(memories) + "\n\n") if memories else ""
            prompt = f"{mem_block}Evidence:\n{result['contextText']}\n\nQuestion: {query}"
            answer = await asyncio.wait_for(_bare_llm(prompt), timeout=_SIMPLE_TIMEOUT_S)
            evidence = result["sources"]

        elif config == "rag_memory_tools":
            from app.agents.planner_agent import PlannerAgent
            from app.agents.research_agent import ResearchAgent
            plan = (await PlannerAgent().run(query, {}))["output"]
            research = (await asyncio.wait_for(
                ResearchAgent().run(query, {"chatId": chat_id or "", "plan": plan, "hasFiles": has_files}),
                timeout=_SIMPLE_TIMEOUT_S,
            ))["output"]
            prompt = f"Evidence:\n{research['evidenceSummary']}\n\nQuestion: {query}"
            answer = await asyncio.wait_for(_bare_llm(prompt), timeout=_SIMPLE_TIMEOUT_S)
            evidence = research["evidence"]

        elif config == "rag_memory_tools_validator":
            from app.agents.planner_agent import PlannerAgent
            from app.agents.research_agent import ResearchAgent
            from app.agents.validation_agent import ValidationAgent
            plan = (await PlannerAgent().run(query, {}))["output"]
            research = (await asyncio.wait_for(
                ResearchAgent().run(query, {"chatId": chat_id or "", "plan": plan, "hasFiles": has_files}),
                timeout=_SIMPLE_TIMEOUT_S,
            ))["output"]
            prompt = f"Evidence:\n{research['evidenceSummary']}\n\nQuestion: {query}"
            answer = await asyncio.wait_for(_bare_llm(prompt), timeout=_SIMPLE_TIMEOUT_S)
            critique = await ValidationAgent().critique(answer, query, research["evidenceSummary"], research["contradictions"])
            evidence = research["evidence"]
            claims = critique.get("claims", [])
            contradictions = research["contradictions"]
            if not critique["pass"]:
                status = "validation_rejected"

        else:  # full
            from app.agents.tool_agent import ToolAgent
            result = await asyncio.wait_for(
                ToolAgent().run(query, {"chatId": chat_id or "", "hasFiles": has_files, "userId": user_id}),
                timeout=_FULL_TIMEOUT_S,
            )
            output = result["output"]
            answer = output["answer"]
            evidence = output["evidence"]
            claims = output.get("reviewIssues", [])
            contradictions = output.get("contradictions", [])
            if output["confidence"]["label"] == "low" and output.get("regenerated"):
                status = "validation_rejected"

    except asyncio.TimeoutError:
        status = "timeout"
    except Exception as err:
        status = _classify_exception(err)
        error_detail = _classify_exception_detail(err)
        answer = f"ERROR: {err}"

    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "id": item["id"],
        "config": config,
        "query": item["query"],
        "paper_category": item.get("paper_category"),
        "gold_route": item.get("gold_route"),
        "gold_answer": item.get("gold_answer"),
        "answer_type": item.get("answer_type"),
        "requires_web": item.get("requires_web", False),
        "answer": answer,
        "status": status,
        "error_detail": error_detail,
        "latency_ms": latency_ms,
        "evidence": evidence,
        "claims": claims,
        "contradictions": contradictions,
    }


async def run_all(split: str, config: str, concurrency: int = 3) -> list[dict]:
    items = load_dataset(split)
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(item):
        async with sem:
            return await run_item(item, config)

    return await asyncio.gather(*[_bounded(item) for item in items])


def _write_raw(records: list[dict], split: str, config: str, run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / f"raw_{split}_{config}.jsonl"
    with open(out_path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return out_path


async def main():
    parser = argparse.ArgumentParser(description="Run the NovaAI eval dataset against a pipeline config.")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--config", choices=CONFIGS, default="full")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--run-id", default=None, help="Reuse an existing run directory name instead of creating a new timestamped one.")
    args = parser.parse_args()

    await db_module.init_db()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / run_id

    records = await run_all(args.split, args.config, args.concurrency)
    out_path = _write_raw(records, args.split, args.config, run_dir)
    print(f"Wrote {len(records)} records to {out_path}")
    print(f"run-id: {run_id}")


if __name__ == "__main__":
    asyncio.run(main())

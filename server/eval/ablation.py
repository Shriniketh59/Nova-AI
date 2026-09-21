"""Runs the ablation study: the same dataset split against each of the six
configurations (baseline LLM -> full NovaAI), computing the paper's six
metrics per configuration from real runs only. Reuses runner.py for
execution and metrics.py for scoring — no separate logic duplicated here."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from . import metrics as M
from .runner import CONFIGS, RUNS_DIR, load_dataset, run_all, _write_raw


def score_records(records: list[dict]) -> dict:
    exact_pairs = [(r["answer"], r["gold_answer"]) for r in records if r.get("answer_type") == "exact" and r.get("gold_answer") is not None]
    hallucination_flags = []
    for r in records:
        claims = r.get("claims") or []
        unsupported = [c for c in claims if isinstance(c, dict) and c.get("supported") is False]
        if claims:
            hallucination_flags.append(bool(unsupported))
        # items with no claims recorded (e.g. baseline_llm config never runs
        # claim extraction) are excluded, not assumed grounded — see report.py

    return {
        "task_completion": M.task_completion_rate([r["status"] for r in records]),
        "exact_match": M.exact_match_rate(exact_pairs),
        "f1": M.f1_token_avg(exact_pairs),
        "hallucination_rate": M.hallucination_rate(hallucination_flags) if hallucination_flags else {
            "hallucination_rate_pct": None, "reason": "config does not run claim-level extraction (only rag_memory_tools_validator and full do)"
        },
        "latency": M.latency_stats([r["latency_ms"] for r in records]),
        "accuracy": {
            "reason": "see exact_match for deterministic items; open-ended (rubric) items are N/A until a "
            "rubric-grading pass is run — not fabricated here",
            "exact_match_based_pct": M.exact_match_rate(exact_pairs)["exact_match_pct"],
        },
    }


async def run_ablation(split: str, concurrency: int = 3) -> dict:
    results = {}
    for config in CONFIGS:
        records = await run_all(split, config, concurrency)
        results[config] = {"records": records, "scores": score_records(records)}
    return results


def build_table(results: dict) -> list[dict]:
    rows = []
    for config, data in results.items():
        s = data["scores"]
        rows.append({
            "Configuration": config,
            "Task Completion (%)": s["task_completion"].get("completion_rate_pct"),
            "Accuracy (Exact-Match-based, %)": s["accuracy"]["exact_match_based_pct"],
            "Hallucination Rate (%)": s["hallucination_rate"].get("hallucination_rate_pct"),
            "Latency (avg ms)": s["latency"].get("avg_ms"),
            "Exact Match (%)": s["exact_match"].get("exact_match_pct"),
            "F1": s["f1"].get("f1_avg"),
        })
    return rows


async def main():
    parser = argparse.ArgumentParser(description="Run the six-configuration ablation study.")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    from app.core import db as db_module
    await db_module.init_db()

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / run_id

    results = await run_ablation(args.split, args.concurrency)
    for config, data in results.items():
        _write_raw(data["records"], args.split, config, run_dir)

    table = build_table(results)
    out_path = run_dir / f"ablation_{args.split}.json"
    with open(out_path, "w") as f:
        json.dump({"table": table, "run_id": run_id}, f, indent=2)

    print(json.dumps(table, indent=2))
    print(f"Wrote ablation results to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())

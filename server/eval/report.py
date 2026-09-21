"""Assembles the final report (structure matching the conference-paper
request's 23 points) from files already produced by runner.py, ablation.py,
classification_eval.py, and error_analysis.py in a given run directory.
This module does not execute the pipeline and does not compute any number
that isn't already present in those files — anything missing is reported
N/A with the reason, never guessed or copied from elsewhere."""

import argparse
import json
from pathlib import Path

from . import metrics as M
from .error_analysis import analyze as analyze_errors
from .runner import RUNS_DIR


def _load_json(path: Path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _load_jsonl(path: Path):
    if not path.exists():
        return None
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def build_report(run_dir: Path, split: str) -> dict:
    ablation = _load_json(run_dir / f"ablation_{split}.json")
    classification = _load_json(run_dir / f"classification_{split}.json")
    full_records = _load_jsonl(run_dir / f"raw_{split}_full.jsonl")
    baseline_records = _load_jsonl(run_dir / f"raw_{split}_baseline_llm.jsonl")

    report = {
        "1_root_causes": [
            "Default text chat path (local_orchestrator) validated answers advisory-only (log, never block); "
            "the hard-gated corrective loop only ran behind a client-side complexity heuristic on a secondary endpoint.",
            "No chunk-level relevance grading before context building; similarity threshold bypassed by any nonzero keyword score.",
            "Corrective retrieval was count-only (forceTopK), not quality/relevance/staleness-driven.",
            "Validation was whole-answer-ratio, not per-claim.",
            "Corrective-loop thresholds hardcoded and scattered across modules.",
            "No evaluation system existed.",
        ],
        "2_files_changed": [
            "server/app/agents/research_agent.py", "server/app/agents/validation_agent.py",
            "server/app/agents/tool_agent.py", "server/app/orchestrator/local_orchestrator.py",
            "server/app/orchestrator/answer_validator.py", "server/app/core/config.py",
        ],
        "3_files_removed": "None. answer_validator.py was retained (rescoped to voice-only) rather than deleted — see plan Execution discipline.",
        "4_corrective_rag_architecture": (
            "retrieve() -> relevance_gate.grade_relevance() -> [insufficient/stale? -> rewrite query, widen top_k, "
            "force web -> retry, bounded MAX_CORRECTIVE_RETRIES] -> filter_relevant() -> detect_duplicates() -> "
            "reranker.rerank() (existing MMR) -> context build -> Qwen generation -> ValidationAgent.critique() "
            "(claim-level) -> regenerate/escalate (bounded) -> final answer."
        ),
        "5_routing_architecture": "intent_router.classify_intent() (unchanged heuristics) -> ToolAgent for all non-greeting/math/coding text turns (both endpoints now share this path).",
        "6_validation_architecture": "ValidationAgent.critique(): heuristic gates (no-evidence, grounding ratio, temporal mismatch, per-claim support) then LLM-judge pass; hard gate on both chat endpoints for text.",
        "7_dataset": _dataset_summary(split),
        "8_confusion_matrix": classification.get("confusion_matrix") if classification else "N/A — classification_eval.py not yet run for this run-id",
        "9_classification_accuracy": classification["metrics"]["accuracy"] if classification else "N/A",
        "10_precision": classification["metrics"]["weighted_avg"]["precision"] if classification else "N/A",
        "11_recall": classification["metrics"]["weighted_avg"]["recall"] if classification else "N/A",
        "12_f1_score_classification": classification["metrics"]["weighted_avg"]["f1"] if classification else "N/A",
        "13_task_completion_rate": _config_metric(ablation, "full", "task_completion"),
        "14_answer_accuracy": _config_metric(ablation, "full", "accuracy"),
        "15_hallucination_rate": _config_metric(ablation, "full", "hallucination_rate"),
        "16_exact_match": _config_metric(ablation, "full", "exact_match"),
        "17_latency": _config_metric(ablation, "full", "latency"),
        "18_rag_vs_ungrounded": _rag_comparison(ablation),
        "19_ablation_results": ablation["table"] if ablation else "N/A — ablation.py not yet run for this run-id",
        "20_error_analysis": analyze_errors(full_records) if full_records else "N/A — no raw_{split}_full.jsonl in this run directory",
        "21_tests": "See `cd server && python -m pytest -q` output recorded separately in the commit/PR history for this change — this report only covers eval numbers, not the unit-test run.",
        "22_limitations": [
            "Rubric-graded (open-ended) items report accuracy via exact-match subset only; no automated open-ended "
            "grading pass has been run, so full 'Accuracy' across all items is N/A until one is.",
            "irrelevant_retrieval, stale_evidence, and rag_context_failure error-analysis buckets require per-chunk "
            "relevance/freshness data not currently persisted in runner.py's raw output — reported as not-auto-detectable, not zero.",
            "Dataset is hand-authored (dev: 12 items, test: 24 items) — small enough that per-category percentages "
            "carry wide confidence intervals; treat as a reproducible pilot evaluation, not a large-N benchmark.",
            "Technical-correctness checking (formulas/complexity) relies on the existing LLM-judge critique prompt, "
            "not a deterministic verifier — no independent ground-truth complexity checker exists in this codebase.",
        ],
        "23_reproduce_commands": [
            "cd server && python -m eval.ablation --split test --run-id <run-id>",
            "cd server && python -m eval.classification_eval --split test",
            "cd server && python -m eval.error_analysis eval/runs/<run-id>/raw_test_full.jsonl",
            "cd server && python -m eval.report --run-id <run-id> --split test",
        ],
    }
    return report


def _dataset_summary(split: str) -> dict:
    from .runner import load_dataset
    try:
        items = load_dataset(split)
    except FileNotFoundError:
        return {"error": f"{split}.jsonl not found"}
    from collections import Counter
    return {
        "size": len(items),
        "by_paper_category": dict(Counter(i.get("paper_category") for i in items)),
        "by_gold_route": dict(Counter(i.get("gold_route") for i in items)),
        "requires_web_count": sum(1 for i in items if i.get("requires_web")),
        "requires_multi_agent_count": sum(1 for i in items if i.get("requires_multi_agent")),
    }


def _config_metric(ablation, config, metric_key):
    if not ablation:
        return "N/A — ablation.py not yet run for this run-id"
    row = next((r for r in ablation["table"] if r["Configuration"] == config), None)
    return row if row else "N/A"


def _rag_comparison(ablation):
    if not ablation:
        return "N/A — ablation.py not yet run for this run-id"
    rows = {r["Configuration"]: r for r in ablation["table"]}
    baseline = rows.get("baseline_llm")
    full = rows.get("full")
    if not baseline or not full:
        return "N/A — baseline_llm or full config missing from ablation table"
    return {"ungrounded_baseline_llm": baseline, "corrective_rag_full": full}


def main():
    parser = argparse.ArgumentParser(description="Assemble the final evaluation report from a run directory's outputs.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    run_dir = RUNS_DIR / args.run_id
    report = build_report(run_dir, args.split)

    out_path = Path(args.out) if args.out else run_dir / f"final_report_{args.split}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Wrote final report to {out_path}")


if __name__ == "__main__":
    main()

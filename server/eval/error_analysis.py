"""Buckets a run's raw records into the failure categories requested for the
paper's error analysis. Several buckets can only be approximated post-hoc
from what runner.py recorded (status, claims, contradictions, evidence) —
this is heuristic, not a ground-truth labeling, and is documented as such
per category below. Each item gets exactly ONE primary bucket, chosen by the
priority order in CATEGORY_PRIORITY, so percentages sum to 100% of items
that had any issue (successes with no flags are excluded, not force-fit into
a category)."""

import argparse
import json
from collections import Counter
from pathlib import Path

from .runner import RUNS_DIR

CATEGORY_PRIORITY = [
    "timeout",
    "budget_exhaustion",
    "memory_error",
    "retrieval_miss",
    "generation_error",
    "tool_failure",
    "coding_failure",
    "validation_miss",
    "hallucination",
    "conflicting_evidence",
    "query_classification_error",
    "irrelevant_retrieval",
    "stale_evidence",
    "rag_context_failure",
]

# Categories this module cannot detect from runner.py's raw output alone —
# they require signals not currently recorded (per-chunk relevance labels,
# freshness scores on final evidence, or gold routing labels merged in
# separately). Left explicit rather than silently reported as zero.
NOT_AUTO_DETECTABLE = {"irrelevant_retrieval", "stale_evidence", "rag_context_failure"}


def _bucket(record: dict) -> str | None:
    status = record.get("status")
    detail = record.get("error_detail")

    if status == "timeout":
        return "timeout"
    if detail == "budget_exhaustion":
        return "budget_exhaustion"
    if detail == "memory_error":
        return "memory_error"
    if detail == "retrieval_miss" or status == "retrieval_failure":
        return "retrieval_miss"
    if detail == "generation_error":
        return "generation_error"
    if status == "tool_failure":
        if record.get("paper_category") == "coding":
            return "coding_failure"
        return "tool_failure"

    claims = record.get("claims") or []
    unsupported = [c for c in claims if isinstance(c, dict) and c.get("supported") is False]
    if status == "success" and unsupported:
        # Whole-answer gate passed but a per-claim check would have caught it.
        return "validation_miss"
    if unsupported:
        return "hallucination"

    if record.get("contradictions"):
        return "conflicting_evidence"

    if record.get("paper_category") == "coding" and status != "success":
        return "coding_failure"

    return None


def analyze(records: list[dict]) -> dict:
    buckets = Counter()
    examples = {}
    for r in records:
        b = _bucket(r)
        if not b:
            continue
        buckets[b] += 1
        examples.setdefault(b, []).append({"id": r["id"], "query": r["query"], "status": r["status"]})

    total_flagged = sum(buckets.values())
    return {
        "total_items": len(records),
        "total_flagged": total_flagged,
        "categories": {
            cat: {
                "count": buckets.get(cat, 0),
                "pct_of_flagged": round(100 * buckets.get(cat, 0) / total_flagged, 2) if total_flagged else None,
                "examples": examples.get(cat, [])[:3],
            }
            for cat in CATEGORY_PRIORITY
        },
        "not_auto_detectable": sorted(NOT_AUTO_DETECTABLE),
        "note": (
            "query_classification_error is 0 here by construction — merge classification_eval.py's "
            "routing_failures list separately, since that requires gold_route comparison this module doesn't have."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Error-bucket a run's raw records.")
    parser.add_argument("raw_file", help="Path to a raw_<split>_<config>.jsonl file from runner.py")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    records = [json.loads(line) for line in open(args.raw_file) if line.strip()]
    result = analyze(records)

    out_path = Path(args.out) if args.out else Path(args.raw_file).with_suffix(".errors.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote error analysis to {out_path}")


if __name__ == "__main__":
    main()

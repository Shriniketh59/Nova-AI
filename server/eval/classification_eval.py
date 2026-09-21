"""Evaluates query routing: runs intent_router.classify_intent() against the
dataset's gold_route and reports the confusion matrix + per-class P/R/F1.
No LLM call involved — classify_intent() is pure regex/heuristic — so this
is fast and deterministic; every run against the same dataset gives the same
result."""

import argparse
import asyncio
import json
from pathlib import Path

from app.orchestrator.intent_router import classify_intent

from .metrics import confusion_matrix, precision_recall_f1_multiclass
from .runner import DATASET_DIR, RUNS_DIR, load_dataset


def evaluate_routing(items: list[dict]) -> dict:
    y_true = []
    y_pred = []
    failures = []
    for item in items:
        gold = item.get("gold_route")
        if not gold:
            continue
        has_files = bool(item.get("fixture_content") or item.get("fixture_conflict"))
        predicted = classify_intent(item["query"], has_files=has_files, has_kb_docs=has_files)
        y_true.append(gold)
        y_pred.append(predicted)
        if predicted != gold:
            failures.append({"id": item["id"], "query": item["query"], "gold_route": gold, "predicted_route": predicted})

    if not y_true:
        return {"error": "no items with gold_route in dataset"}

    return {
        "confusion_matrix": confusion_matrix(y_true, y_pred),
        "metrics": precision_recall_f1_multiclass(y_true, y_pred),
        "total_samples": len(y_true),
        "correctly_routed": sum(1 for t, p in zip(y_true, y_pred) if t == p),
        "incorrectly_routed": sum(1 for t, p in zip(y_true, y_pred) if t != p),
        "routing_failures": failures,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate NovaAI query routing against the eval dataset.")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    items = load_dataset(args.split)
    result = evaluate_routing(items)

    out_path = Path(args.out) if args.out else RUNS_DIR / f"classification_{args.split}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Wrote classification eval to {out_path}")
    print(json.dumps({"accuracy": result["metrics"]["accuracy"], "macro_f1": result["metrics"]["macro_avg"]["f1"]}, indent=2))


if __name__ == "__main__":
    main()

"""Metric implementations for the NovaAI evaluation. Every function here is a
pure calculation over inputs the caller measured — nothing in this module
invents or assumes a result; a caller with no data for a metric should not
call it and should report "N/A" with a reason instead (see report.py)."""

import re
import statistics
from collections import Counter


def normalize_answer(text: str) -> str:
    """Whitespace + case normalization only — never alters content in a way
    that could hide a factual difference (no stripping of numbers/units)."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def exact_match(prediction: str, gold: str) -> bool:
    return normalize_answer(prediction) == normalize_answer(gold)


def exact_match_rate(pairs: list[tuple[str, str]]) -> dict:
    """pairs: list of (prediction, gold). Returns rate as a percentage plus counts."""
    if not pairs:
        return {"exact_match_pct": None, "matched": 0, "total": 0, "reason": "no exact-match-eligible items"}
    matched = sum(1 for pred, gold in pairs if exact_match(pred, gold))
    return {"exact_match_pct": round(100 * matched / len(pairs), 2), "matched": matched, "total": len(pairs)}


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_answer(text))


def f1_token(prediction: str, gold: str) -> float:
    """Token-level F1 (SQuAD-style) between prediction and gold answer."""
    pred_tokens = _tokens(prediction)
    gold_tokens = _tokens(gold)
    if not pred_tokens and not gold_tokens:
        return 1.0
    if not pred_tokens or not gold_tokens:
        return 0.0
    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    return round(2 * precision * recall / (precision + recall), 4)


def f1_token_avg(pairs: list[tuple[str, str]]) -> dict:
    if not pairs:
        return {"f1_avg": None, "total": 0, "reason": "no F1-eligible items"}
    scores = [f1_token(pred, gold) for pred, gold in pairs]
    return {"f1_avg": round(sum(scores) / len(scores), 4), "total": len(scores), "per_item": [round(s, 4) for s in scores]}


def precision_recall_f1_multiclass(y_true: list[str], y_pred: list[str]) -> dict:
    """Per-class precision/recall/F1/support, plus macro and weighted
    averages, for the routing-classification evaluation."""
    if len(y_true) != len(y_pred) or not y_true:
        return {"error": "y_true/y_pred length mismatch or empty", "classes": {}}

    classes = sorted(set(y_true) | set(y_pred))
    per_class = {}
    for c in classes:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        support = sum(1 for t in y_true if t == c)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_class[c] = {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "support": support}

    total = len(y_true)
    macro_p = round(sum(v["precision"] for v in per_class.values()) / len(classes), 4)
    macro_r = round(sum(v["recall"] for v in per_class.values()) / len(classes), 4)
    macro_f1 = round(sum(v["f1"] for v in per_class.values()) / len(classes), 4)
    weighted_p = round(sum(v["precision"] * v["support"] for v in per_class.values()) / total, 4)
    weighted_r = round(sum(v["recall"] * v["support"] for v in per_class.values()) / total, 4)
    weighted_f1 = round(sum(v["f1"] * v["support"] for v in per_class.values()) / total, 4)
    accuracy = round(sum(1 for t, p in zip(y_true, y_pred) if t == p) / total, 4)

    return {
        "classes": per_class,
        "accuracy": accuracy,
        "macro_avg": {"precision": macro_p, "recall": macro_r, "f1": macro_f1},
        "weighted_avg": {"precision": weighted_p, "recall": weighted_r, "f1": weighted_f1},
        "total_samples": total,
    }


def confusion_matrix(y_true: list[str], y_pred: list[str]) -> dict:
    classes = sorted(set(y_true) | set(y_pred))
    matrix = {c: {c2: 0 for c2 in classes} for c in classes}
    for t, p in zip(y_true, y_pred):
        matrix[t][p] += 1
    return {"classes": classes, "matrix": matrix}


def hallucination_rate(flags: list[bool]) -> dict:
    """flags: one bool per evaluated output — True if it contained at least
    one unsupported/contradictory claim (from claim-level validation output,
    e.g. ValidationAgent.critique()'s 'claims' field or an explicit
    unsupported_claim/contradiction issue)."""
    if not flags:
        return {"hallucination_rate_pct": None, "hallucinated": 0, "total": 0, "reason": "no evaluated outputs"}
    hallucinated = sum(1 for f in flags if f)
    return {
        "hallucination_rate_pct": round(100 * hallucinated / len(flags), 2),
        "hallucinated": hallucinated,
        "grounded": len(flags) - hallucinated,
        "total": len(flags),
    }


def latency_stats(latencies_ms: list[float]) -> dict:
    if not latencies_ms:
        return {"reason": "no latency samples"}
    sorted_lat = sorted(latencies_ms)
    n = len(sorted_lat)
    p95_idx = min(n - 1, int(round(0.95 * (n - 1))))
    return {
        "avg_ms": round(sum(sorted_lat) / n, 1),
        "median_ms": round(statistics.median(sorted_lat), 1),
        "min_ms": round(sorted_lat[0], 1),
        "max_ms": round(sorted_lat[-1], 1),
        "p95_ms": round(sorted_lat[p95_idx], 1),
        "n": n,
    }


def task_completion_rate(statuses: list[str]) -> dict:
    """statuses: one of success|partial|failed|timeout|validation_rejected|
    tool_failure|retrieval_failure per task, as assigned by runner.py per the
    definitions in its docstring."""
    if not statuses:
        return {"completion_rate_pct": None, "reason": "no tasks run"}
    counts = Counter(statuses)
    total = len(statuses)
    successful = counts.get("success", 0)
    return {
        "completion_rate_pct": round(100 * successful / total, 2),
        "total_tasks": total,
        "successful": successful,
        "failed": counts.get("failed", 0),
        "partial": counts.get("partial", 0),
        "timeout": counts.get("timeout", 0),
        "validation_rejected": counts.get("validation_rejected", 0),
        "tool_failure": counts.get("tool_failure", 0),
        "retrieval_failure": counts.get("retrieval_failure", 0),
    }

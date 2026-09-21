import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval import metrics as M


def test_exact_match_normalizes_whitespace_and_case():
    assert M.exact_match("  Paris  ", "paris") is True
    assert M.exact_match("Tokyo", "Osaka") is False


def test_exact_match_rate_empty_pairs_is_na():
    result = M.exact_match_rate([])
    assert result["exact_match_pct"] is None


def test_exact_match_rate_counts_correctly():
    pairs = [("Paris", "Paris"), ("London", "Paris"), ("4", "4")]
    result = M.exact_match_rate(pairs)
    assert result["matched"] == 2
    assert result["total"] == 3
    assert result["exact_match_pct"] == round(100 * 2 / 3, 2)


def test_f1_token_identical_is_one():
    assert M.f1_token("the quick brown fox", "the quick brown fox") == 1.0


def test_f1_token_disjoint_is_zero():
    assert M.f1_token("apple banana", "car truck") == 0.0


def test_f1_token_partial_overlap():
    score = M.f1_token("the quick fox", "the quick brown fox")
    assert 0 < score < 1


def test_precision_recall_f1_multiclass_perfect():
    y_true = ["a", "b", "a", "b"]
    y_pred = ["a", "b", "a", "b"]
    result = M.precision_recall_f1_multiclass(y_true, y_pred)
    assert result["accuracy"] == 1.0
    assert result["macro_avg"]["f1"] == 1.0


def test_precision_recall_f1_multiclass_with_errors():
    y_true = ["a", "a", "b", "b"]
    y_pred = ["a", "b", "b", "b"]
    result = M.precision_recall_f1_multiclass(y_true, y_pred)
    assert result["accuracy"] == 0.75
    assert result["classes"]["a"]["recall"] == 0.5
    assert result["classes"]["b"]["recall"] == 1.0


def test_confusion_matrix_shape():
    y_true = ["a", "b"]
    y_pred = ["a", "a"]
    cm = M.confusion_matrix(y_true, y_pred)
    assert cm["matrix"]["b"]["a"] == 1
    assert cm["matrix"]["a"]["a"] == 1


def test_hallucination_rate_basic():
    result = M.hallucination_rate([True, False, False, True])
    assert result["hallucinated"] == 2
    assert result["hallucination_rate_pct"] == 50.0


def test_hallucination_rate_empty_is_na():
    result = M.hallucination_rate([])
    assert result["hallucination_rate_pct"] is None


def test_latency_stats_basic():
    result = M.latency_stats([100, 200, 300, 400, 500])
    assert result["min_ms"] == 100
    assert result["max_ms"] == 500
    assert result["median_ms"] == 300


def test_task_completion_rate_basic():
    statuses = ["success", "success", "failed", "timeout"]
    result = M.task_completion_rate(statuses)
    assert result["successful"] == 2
    assert result["total_tasks"] == 4
    assert result["completion_rate_pct"] == 50.0

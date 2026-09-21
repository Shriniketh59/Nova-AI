# Evaluation dataset schema

Each `.jsonl` file is one JSON object per line:

```json
{
  "id": "doc-001",
  "query": "What does the uploaded spec say the max chunk size is?",
  "paper_category": "rag_document",
  "gold_route": "doc_query",
  "requires_multi_agent": false,
  "gold_answer": "800 characters",
  "answer_type": "exact",
  "requires_web": false,
  "notes": "Answerable from tests/fixtures upload corpus; deterministic gold answer."
}
```

## Fields

- `id` — stable identifier, `<category-prefix>-<3digit>`.
- `query` — the input text sent to the pipeline under evaluation.
- `paper_category` — one of the conference paper's six routing classes:
  `rag_document`, `current_web`, `calculation`, `coding`, `stable_knowledge`, `complex_multi_agent`.
- `gold_route` — the actual NovaAI router intent (`intent_router.classify_intent()`)
  this query should land on: `greeting | math | coding | current_info | doc_query | general`.
  **Note on `complex_multi_agent`**: NovaAI's router has no 7th "complex" intent —
  a complex/multi-step query still classifies into one of the five real intents,
  and (since the CRAG unification) *every* non-greeting/math/coding text turn now
  runs the full multi-agent ToolAgent pipeline regardless of complexity. So
  `paper_category: complex_multi_agent` items get a normal `gold_route` and are
  additionally flagged `requires_multi_agent: true` — that flag is checked
  against `regenerated`/`sourceCount`/stage-trace evidence in the run output,
  not against a routing class that doesn't exist in the router. This mapping is
  documented here explicitly rather than inventing a category the code doesn't have.
- `requires_multi_agent` — bool, whether this item is a paper-defined "complex" case.
- `gold_answer` — reference answer, or `null` for open-ended items (those are
  graded by rubric — see `runner.py`'s `_rubric_grade`).
- `answer_type` — `exact` (deterministic, scored by exact_match/F1) or
  `rubric` (open-ended, graded via claim-matching against gold evidence).
- `requires_web` — bool, whether the item needs live web evidence to answer
  correctly (used for the RAG-vs-ungrounded and staleness-sensitive slices).
- `notes` — free text, e.g. why an item is insufficient-evidence/conflicting/
  hallucination-sensitive by design.

## Splits

- `dev.jsonl` — used only while tuning thresholds/prompts (relevance_gate,
  validation_agent, tool_agent bounds). Never scored for the paper's reported
  numbers.
- `test.jsonl` — held out, scored once implementation is frozen. This is the
  file `runner.py --split test` reads for the numbers in the final report.

Both splits were hand-authored for this project (not copied from a public
benchmark), covering: RAG/document questions, current-info questions,
calculations, coding problems, stable general knowledge, complex multi-step
tasks, insufficient-evidence questions, conflicting-document questions, and
hallucination-sensitive questions, per the six `paper_category` classes above.

from ..core.config import OLLAMA_MODEL
from ..services.task_router import classify_topic
from ..utils.completion_guard import generate_with_continuation
from .base_agent import BaseAgent

TOPIC_GUIDANCE = {
    "medical": "This is a medical topic — be precise, note uncertainty, avoid definitive diagnosis/dosage claims not directly supported by evidence.",
    "legal": "This is a legal topic — be precise about jurisdiction-dependence, avoid stating case-specific legal advice as fact.",
    "biography": "This is a biographical topic — verify names/dates/roles against evidence rather than general knowledge.",
    "news": "This is a current-events topic — flag if evidence may be outdated and avoid presenting stale info as current.",
    "math": "This is a math/computation topic — show the calculation steps, don't just state the result.",
    "research": "This is a research-depth topic — synthesize across sources rather than restating one.",
}


def _build_reasoning_prompt(question: str, plan: dict, evidence_summary: str, contradictions: list, memories: list, feedback):
    contradiction_note = (
        "\nWarning — these sources disagree, address this explicitly:\n"
        + "\n".join(f"- {c['sourceA']} vs {c['sourceB']}" for c in contradictions) + "\n"
        if contradictions else ""
    )

    memory_note = (
        "\nRelevant context from earlier in this conversation:\n" + "\n".join(memories) + "\n"
        if memories else ""
    )

    feedback_note = f"\nYour previous draft had issues, fix them: {feedback}\n" if feedback else ""

    topic = classify_topic(question)
    topic_note = f"\nDomain note: {TOPIC_GUIDANCE[topic]}\n" if topic in TOPIC_GUIDANCE else ""

    structure_note = (
        "Reply naturally in 1-2 sentences, no section headings."
        if plan.get("taskType") == "greeting"
        else """Structure your answer with these markdown sections, in order:
## Direct Answer
One or two sentences answering the question head-on.
## Detailed Explanation
Full reasoning, addressing every part of a multi-part question.
## Key Findings
A short bullet list of the most important facts from the evidence.
## Conclusion
A closing takeaway sentence."""
    )

    steps = " -> ".join(plan.get("steps", []))

    return f"""Question: {question}

Intent: {plan.get('intent', '')}
Planned approach: {steps}
{topic_note}{memory_note}
Evidence gathered:
{evidence_summary}
{contradiction_note}{feedback_note}
Think step by step before writing:
1. What do the sources actually say, in relation to the question?
2. Are there patterns or agreement across sources?
3. If this is a comparison, weigh the options explicitly.
4. State your conclusion clearly and directly.

{structure_note}

Write ONLY the final answer text (no "Step 1:" labels, no meta-commentary) — but make sure it reflects real reasoning over the evidence above, not a generic response."""


class ReasoningAgent(BaseAgent):
    """Third stage: Evidence Analysis -> Reasoning. Takes the Planner's plan
    and the Research Agent's evidence list and produces a reasoned draft answer."""

    def __init__(self):
        super().__init__("ReasoningAgent")

    async def run(self, question: str, context: dict | None = None) -> dict:
        context = context or {}
        plan = context.get("plan", {})
        evidence_summary = context.get("evidenceSummary", "")
        contradictions = context.get("contradictions", [])
        memories = context.get("memories", [])
        feedback = context.get("feedback")
        try:
            prompt = _build_reasoning_prompt(question, plan, evidence_summary, contradictions, memories, feedback)
            answer = await generate_with_continuation(
                [{"role": "user", "content": prompt}],
                model=OLLAMA_MODEL,
                num_predict=4096,
                temperature=0.4,
                require_sections=plan.get("taskType") != "greeting",
            )
            return {"success": True, "output": {"answer": answer}}
        except Exception as err:
            return {"success": False, "output": {"answer": ""}, "error": str(err)}

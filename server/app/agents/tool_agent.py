import time

from ..core.config import OLLAMA_MODEL
from ..core.logger import logger
from ..services.task_router import classify_topic
from ..utils.completion_guard import generate_with_continuation
from ..utils.context_manager import get_conversation_context
from .base_agent import BaseAgent
from .memory_agent import memory_agent
from .planner_agent import PlannerAgent
from .research_agent import ResearchAgent
from .validation_agent import ValidationAgent

MAX_REGENERATION_ATTEMPTS = 1
MAX_EVIDENCE_ESCALATIONS = 1

VERIFICATION_FAILURE_MESSAGE = "I couldn't verify this information from reliable sources."

TOPIC_GUIDANCE = {
    "medical": "This is a medical topic — be precise, note uncertainty, avoid definitive diagnosis/dosage claims not directly supported by evidence.",
    "legal": "This is a legal topic — be precise about jurisdiction-dependence, avoid stating case-specific legal advice as fact.",
    "biography": "This is a biographical topic — verify names/dates/roles against evidence rather than general knowledge.",
    "news": "This is a current-events topic — flag if evidence may be outdated and avoid presenting stale info as current.",
    "math": "This is a math/computation topic — show the calculation steps, don't just state the result.",
    "research": "This is a research-depth topic — synthesize across sources rather than restating one.",
}


def _build_verification_failure_answer(evidence: list[dict]) -> str:
    available = "\n".join(f"- {e.get('title') or e.get('filename') or 'source'}" for e in evidence[:3])
    if available:
        return f"{VERIFICATION_FAILURE_MESSAGE}\n\nWhat's available, for reference, is limited and unconfirmed:\n{available}"
    return VERIFICATION_FAILURE_MESSAGE


def _build_reasoning_prompt(question: str, plan: dict, evidence_summary: str, contradictions: list, memories: list, feedback):
    contradiction_note = (
        "\nWarning — these sources disagree, address this explicitly:\n"
        + "\n".join(f"- {c['sourceA']} vs {c['sourceB']}" for c in contradictions) + "\n"
        if contradictions else ""
    )

    memory_note = (
        "\n[RELEVANT CONVERSATION CONTEXT (Follow-up to previous turn)]\n"
        + "\n".join(memories)
        + "\nNote: Context from earlier in this conversation is solely for resolving references in follow-up questions. Answer ONLY the current question.\n"
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


class ToolAgent(BaseAgent):
    """Critical-thinking pipeline orchestrator:
    Question -> Intent Analysis -> Task Classification (Planner)
             -> Memory Retrieval
             -> RAG Retrieval + Evidence Analysis (Research)
             -> Reasoning
             -> Self Review (regenerate once if it fails)
             -> Final Answer"""

    def __init__(self, planner=None, research=None, review=None):
        super().__init__("ToolAgent")
        self.planner = planner or PlannerAgent()
        self.research = research or ResearchAgent()
        self.review = review or ValidationAgent()

    async def _reason(self, question: str, context: dict) -> dict:
        """Evidence Analysis -> Reasoning stage: takes the plan and evidence
        and produces a reasoned draft answer. Inlined from the former
        ReasoningAgent — this is a pipeline stage of the Tool agent, not a
        separate agent."""
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

    async def run(self, question: str, context: dict | None = None) -> dict:
        context = context or {}
        chat_id = context.get("chatId")
        raw_on_stage = context.get("onStage", lambda name: None)
        has_files = context.get("hasFiles", False)

        stage_start = time.time()
        last_stage = "start"

        def on_stage(name):
            nonlocal stage_start, last_stage
            logger.info("tool_agent.stage", {"chatId": chat_id, "stage": last_stage, "latencyMs": round((time.time() - stage_start) * 1000)})
            stage_start = time.time()
            last_stage = name
            raw_on_stage(name)

        on_stage("planning")

        import asyncio
        from ..orchestrator.context_filter import detect_follow_up
        from ..core import db

        history = []
        try:
            exclude_id = context.get("excludeMessageId")
            if chat_id:
                res = await db.query(
                    "SELECT role, content FROM messages WHERE chat_id = $1 AND ($2::uuid IS NULL OR id != $2) ORDER BY created_at DESC LIMIT 8",
                    [chat_id, exclude_id],
                )
                history = list(reversed(res["rows"]))
        except Exception:
            history = []

        is_follow_up, follow_up_context, meta = detect_follow_up(question, history)

        async def _safe_memories():
            try:
                from ..core.config import DEFAULT_USER_ID
                uid = context.get("userId") or DEFAULT_USER_ID
                return await memory_agent.get_relevant_memories(chat_id, question, context.get("excludeMessageId"), 3, user_id=uid)
            except Exception:
                return []

        async def _safe_conv_context():
            if not is_follow_up:
                return ""
            try:
                return follow_up_context or await get_conversation_context(chat_id)
            except Exception:
                return ""

        memories_task = asyncio.create_task(_safe_memories())
        conv_context_task = asyncio.create_task(_safe_conv_context())

        planner_result = await self.planner.run(question, context)
        plan = planner_result["output"]
        on_stage("memory")
        memories_result, conversation_context = await asyncio.gather(memories_task, conv_context_task)
        memories = [conversation_context] if conversation_context else memories_result

        on_stage("researching")
        research_result = await self.research.run(question, {"chatId": chat_id, "plan": plan, "hasFiles": has_files, "memories": memories})
        output = research_result["output"]
        evidence, evidence_summary, contradictions = output["evidence"], output["evidenceSummary"], output["contradictions"]
        doc_confidence, source_count, min_sources = output["docConfidence"], output["sourceCount"], output["minSources"]
        trust_tiers, category = output["trustTiers"], output["category"]

        on_stage("reasoning")
        reasoning_result = await self._reason(question, {"plan": plan, "evidenceSummary": evidence_summary, "contradictions": contradictions, "memories": memories})
        answer = reasoning_result["output"]["answer"]

        on_stage("reviewing")
        critique = await self.review.critique(answer, question, evidence_summary, contradictions)

        evidence_escalations = 0
        while critique["needsMoreEvidence"] and source_count < min_sources and evidence_escalations < MAX_EVIDENCE_ESCALATIONS:
            evidence_escalations += 1
            on_stage("researching")
            research_result = await self.research.run(question, {"chatId": chat_id, "plan": plan, "hasFiles": has_files, "memories": memories, "forceTopK": min_sources * 2})
            output = research_result["output"]
            evidence, evidence_summary, contradictions = output["evidence"], output["evidenceSummary"], output["contradictions"]
            doc_confidence, source_count, min_sources = output["docConfidence"], output["sourceCount"], output["minSources"]
            trust_tiers, category = output["trustTiers"], output["category"]

            on_stage("reasoning")
            reasoning_result = await self._reason(question, {"plan": plan, "evidenceSummary": evidence_summary, "contradictions": contradictions, "memories": memories})
            answer = reasoning_result["output"]["answer"]

            on_stage("reviewing")
            critique = await self.review.critique(answer, question, evidence_summary, contradictions)

        verification_failed = critique["needsMoreEvidence"] and source_count < min_sources and evidence_escalations >= MAX_EVIDENCE_ESCALATIONS
        if verification_failed:
            answer = _build_verification_failure_answer(evidence)

        attempts = 0
        while not verification_failed and not critique["pass"] and attempts < MAX_REGENERATION_ATTEMPTS:
            attempts += 1
            on_stage("regenerating")
            reasoning_result = await self._reason(question, {
                "plan": plan, "evidenceSummary": evidence_summary, "contradictions": contradictions,
                "memories": memories, "feedback": "; ".join(critique["issues"]),
            })
            answer = reasoning_result["output"]["answer"]
            critique = await self.review.critique(answer, question, evidence_summary, contradictions)

        # Simple inline confidence — no longer uses confidence_engine module
        if verification_failed:
            confidence = {"score": 0, "label": "low", "reason": "Evidence remained insufficient after broadening retrieval."}
        else:
            blended_score = (
                round((source_count * 8 + 30 + critique["confidenceScore"]) / 2)
                if critique["pass"]
                else max(0, min(50, critique["confidenceScore"]) - 15)
            )
            blended_score = max(0, min(100, blended_score))
            confidence = {
                "score": blended_score,
                "label": "high" if blended_score >= 70 else "medium" if blended_score >= 30 else "low",
                "reason": critique.get("confidenceReason") or f"{source_count} source(s) used.",
            }

        logger.info("tool_agent.stage", {"chatId": chat_id, "stage": last_stage, "latencyMs": round((time.time() - stage_start) * 1000)})

        return {
            "success": True,
            "output": {
                "answer": answer,
                "plan": plan,
                "evidence": evidence,
                "sourceCount": source_count,
                "contradictions": contradictions,
                "confidence": confidence,
                "docConfidence": doc_confidence,
                "reviewIssues": critique["issues"],
                "regenerated": attempts > 0 or evidence_escalations > 0,
            },
        }

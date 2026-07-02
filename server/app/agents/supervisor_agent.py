import time

from ..core.logger import logger
from ..retrieval.confidence_engine import compute_answer_confidence
from ..utils.context_manager import get_conversation_context
from .base_agent import BaseAgent
from .memory_agent import memory_agent
from .planner_agent import PlannerAgent
from .reasoning_agent import ReasoningAgent
from .research_agent import ResearchAgent
from .review_agent import ReviewAgent

MAX_REGENERATION_ATTEMPTS = 1
MAX_EVIDENCE_ESCALATIONS = 1

VERIFICATION_FAILURE_MESSAGE = "I couldn't verify this information from reliable sources."


def _build_verification_failure_answer(evidence: list[dict]) -> str:
    available = "\n".join(f"- {e.get('title') or e.get('filename') or 'source'}" for e in evidence[:3])
    if available:
        return f"{VERIFICATION_FAILURE_MESSAGE}\n\nWhat's available, for reference, is limited and unconfirmed:\n{available}"
    return VERIFICATION_FAILURE_MESSAGE


class SupervisorAgent(BaseAgent):
    """Critical-thinking pipeline orchestrator:
    Question -> Intent Analysis -> Task Classification (Planner)
             -> Memory Retrieval
             -> RAG Retrieval + Evidence Analysis (Research)
             -> Reasoning
             -> Self Review (regenerate once if it fails)
             -> Final Answer"""

    def __init__(self, planner=None, research=None, reasoning=None, review=None):
        super().__init__("SupervisorAgent")
        self.planner = planner or PlannerAgent()
        self.research = research or ResearchAgent()
        self.reasoning = reasoning or ReasoningAgent()
        self.review = review or ReviewAgent()

    async def run(self, question: str, context: dict | None = None) -> dict:
        context = context or {}
        chat_id = context.get("chatId")
        raw_on_stage = context.get("onStage", lambda name: None)
        has_files = context.get("hasFiles", False)

        stage_start = time.time()
        last_stage = "start"

        def on_stage(name):
            nonlocal stage_start, last_stage
            logger.info("supervisor.stage", {"chatId": chat_id, "stage": last_stage, "latencyMs": round((time.time() - stage_start) * 1000)})
            stage_start = time.time()
            last_stage = name
            raw_on_stage(name)

        on_stage("planning")

        import asyncio

        async def _safe_memories():
            try:
                return await memory_agent.get_relevant_memories(chat_id, question, context.get("excludeMessageId"), 3)
            except Exception:
                return []

        async def _safe_conv_context():
            try:
                return await get_conversation_context(chat_id)
            except Exception:
                return ""

        memories_task = asyncio.create_task(_safe_memories())
        conv_context_task = asyncio.create_task(_safe_conv_context())

        planner_result = await self.planner.run(question, context)
        plan = planner_result["output"]
        on_stage("memory")
        memories_result, conversation_context = await asyncio.gather(memories_task, conv_context_task)
        memories = [*memories_result, conversation_context] if conversation_context else memories_result

        on_stage("researching")
        research_result = await self.research.run(question, {"chatId": chat_id, "plan": plan, "hasFiles": has_files, "memories": memories})
        output = research_result["output"]
        evidence, evidence_summary, contradictions = output["evidence"], output["evidenceSummary"], output["contradictions"]
        doc_confidence, source_count, min_sources = output["docConfidence"], output["sourceCount"], output["minSources"]
        trust_tiers, category = output["trustTiers"], output["category"]

        on_stage("reasoning")
        reasoning_result = await self.reasoning.run(question, {"plan": plan, "evidenceSummary": evidence_summary, "contradictions": contradictions, "memories": memories})
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
            reasoning_result = await self.reasoning.run(question, {"plan": plan, "evidenceSummary": evidence_summary, "contradictions": contradictions, "memories": memories})
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
            reasoning_result = await self.reasoning.run(question, {
                "plan": plan, "evidenceSummary": evidence_summary, "contradictions": contradictions,
                "memories": memories, "feedback": "; ".join(critique["issues"]),
            })
            answer = reasoning_result["output"]["answer"]
            critique = await self.review.critique(answer, question, evidence_summary, contradictions)

        grounded_confidence = compute_answer_confidence(
            source_count=source_count,
            contradictions=contradictions,
            doc_confidence=doc_confidence,
            has_web_sources=any(e.get("type") == "web" for e in evidence),
            trust_tiers=trust_tiers,
            category=category,
        )
        blended_score = (
            round((grounded_confidence["score"] + critique["confidenceScore"]) / 2)
            if critique["pass"]
            else max(0, min(grounded_confidence["score"], critique["confidenceScore"]) - 15)
        )
        confidence = (
            {"score": 0, "label": "low", "reason": "Evidence remained insufficient after broadening retrieval — stated rather than guessed."}
            if verification_failed
            else {
                "score": blended_score,
                "label": "high" if blended_score >= 70 else "medium" if blended_score >= 30 else "low",
                "reason": critique["confidenceReason"] or grounded_confidence["reason"],
            }
        )

        logger.info("supervisor.stage", {"chatId": chat_id, "stage": last_stage, "latencyMs": round((time.time() - stage_start) * 1000)})

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

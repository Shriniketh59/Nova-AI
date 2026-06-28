import { BaseAgent } from './baseAgent.js';
import { PlannerAgent } from './plannerAgent.js';
import { ResearchAgent } from './researchAgent.js';
import { ReasoningAgent } from './reasoningAgent.js';
import { ReviewAgent } from './reviewAgent.js';
import { memoryAgent } from './memoryAgent.js';
import { computeAnswerConfidence } from '../retrieval/confidenceEngine.js';
import logger from '../utils/logger.js';
import { getConversationContext } from '../utils/contextManager.js';

const MAX_REGENERATION_ATTEMPTS = 1; // bounds the review->reasoning loop so a stubborn critique can't infinite-loop
const MAX_EVIDENCE_ESCALATIONS = 1; // bounds the "not enough evidence, retrieve more" loop

const VERIFICATION_FAILURE_MESSAGE = "I couldn't verify this information from reliable sources.";

// Built when more retrieval already happened once and still didn't resolve
// the critique's "needs more evidence" flag — escalating again wouldn't
// help, so state the gap honestly instead of returning a possibly-confident
// wrong answer (the exact failure mode this phase exists to close).
function buildVerificationFailureAnswer(evidence) {
  const available = evidence.slice(0, 3).map(e => `- ${e.title || e.filename || 'source'}`).join('\n');
  return available
    ? `${VERIFICATION_FAILURE_MESSAGE}\n\nWhat's available, for reference, is limited and unconfirmed:\n${available}`
    : VERIFICATION_FAILURE_MESSAGE;
}

// Critical-thinking pipeline orchestrator:
//   Question -> Intent Analysis -> Task Classification (Planner)
//            -> Memory Retrieval
//            -> RAG Retrieval + Evidence Analysis (Research)
//            -> Reasoning
//            -> Self Review (regenerate once if it fails)
//            -> Final Answer
// Each stage is a real LLM/retrieval call — no shortcuts — per this
// session's priority order: Reasoning > Evidence > Accuracy > Speed > Creativity.
// `context.onStage(name)` is called before each stage so the route layer can
// stream progress ("Planning...", "Researching...") instead of leaving the
// UI frozen for the 1-3 minutes this pipeline can take.
export class SupervisorAgent extends BaseAgent {
  constructor(agents = {}) {
    super('SupervisorAgent');
    this.planner = agents.planner || new PlannerAgent();
    this.research = agents.research || new ResearchAgent();
    this.reasoning = agents.reasoning || new ReasoningAgent();
    this.review = agents.review || new ReviewAgent();
  }

  async run(question, context = {}) {
    const { chatId, onStage: rawOnStage = () => {}, hasFiles = false } = context;

    // Wraps the caller's onStage with per-stage latency logging — turns the
    // existing progress-streaming hook into observability for free, no new
    // call sites needed at each stage transition below.
    let stageStart = Date.now();
    let lastStage = 'start';
    const onStage = (name) => {
      logger.info('supervisor.stage', { chatId, stage: lastStage, latencyMs: Date.now() - stageStart });
      stageStart = Date.now();
      lastStage = name;
      rawOnStage(name);
    };

    // Memory lookup doesn't depend on the plan, so kick it off alongside
    // planning instead of after it — shaves a full round-trip off latency.
    onStage('planning');
    const memoriesPromise = memoryAgent.getRelevantMemories(chatId, question, context.excludeMessageId, 3).catch(() => []);
    const conversationContextPromise = getConversationContext(chatId).catch(() => '');
    const plannerResult = await this.planner.run(question, context);
    const plan = plannerResult.output;
    onStage('memory');
    const [memoriesResult, conversationContext] = await Promise.all([memoriesPromise, conversationContextPromise]);
    const memories = conversationContext ? [...memoriesResult, conversationContext] : memoriesResult;

    onStage('researching');
    let researchResult = await this.research.run(question, { chatId, plan, hasFiles, memories });
    let { evidence, evidenceSummary, contradictions, docConfidence, sourceCount, minSources, trustTiers, category } = researchResult.output;

    onStage('reasoning');
    let reasoningResult = await this.reasoning.run(question, { plan, evidenceSummary, contradictions, memories });
    let answer = reasoningResult.output.answer;

    onStage('reviewing');
    let critique = await this.review.critique(answer, { question, evidenceSummary, contradictions });

    // "If evidence is insufficient, retrieve more before answering" — widen
    // the retrieval tier once and rebuild evidence/answer from scratch,
    // distinct from the regeneration loop below (which just rewrites the
    // answer against evidence already gathered).
    let evidenceEscalations = 0;
    while (critique.needsMoreEvidence && sourceCount < minSources && evidenceEscalations < MAX_EVIDENCE_ESCALATIONS) {
      evidenceEscalations++;
      onStage('researching');
      researchResult = await this.research.run(question, { chatId, plan, hasFiles, memories, forceTopK: minSources * 2 });
      ({ evidence, evidenceSummary, contradictions, docConfidence, sourceCount, minSources, trustTiers, category } = researchResult.output);

      onStage('reasoning');
      reasoningResult = await this.reasoning.run(question, { plan, evidenceSummary, contradictions, memories });
      answer = reasoningResult.output.answer;

      onStage('reviewing');
      critique = await this.review.critique(answer, { question, evidenceSummary, contradictions });
    }

    // Escalation ran its bound and evidence is still below the tier's
    // minimum with the critique still flagging it — more retrieval already
    // failed to help, so don't let the LLM guess. State the gap honestly.
    const verificationFailed = critique.needsMoreEvidence && sourceCount < minSources && evidenceEscalations >= MAX_EVIDENCE_ESCALATIONS;
    if (verificationFailed) {
      answer = buildVerificationFailureAnswer(evidence);
    }

    let attempts = 0;
    while (!verificationFailed && !critique.pass && attempts < MAX_REGENERATION_ATTEMPTS) {
      attempts++;
      onStage('regenerating');
      reasoningResult = await this.reasoning.run(question, {
        plan, evidenceSummary, contradictions, memories,
        feedback: critique.issues.join('; ')
      });
      answer = reasoningResult.output.answer;
      critique = await this.review.critique(answer, { question, evidenceSummary, contradictions });
    }

    // Confidence is grounded in source count/agreement/contradictions —
    // never in raw vector similarity. The LLM critique's own confidenceScore
    // factors in too (it's the only signal that catches hallucination/logic
    // issues a count-based formula can't see), but capped down when the
    // critique didn't pass cleanly.
    const groundedConfidence = computeAnswerConfidence({
      sourceCount,
      contradictions,
      docConfidence,
      hasWebSources: evidence.some(e => e.type === 'web'),
      trustTiers,
      category
    });
    const blendedScore = critique.pass
      ? Math.round((groundedConfidence.score + critique.confidenceScore) / 2)
      : Math.max(0, Math.min(groundedConfidence.score, critique.confidenceScore) - 15);
    const confidence = verificationFailed
      ? { score: 0, label: 'low', reason: 'Evidence remained insufficient after broadening retrieval — stated rather than guessed.' }
      : {
          score: blendedScore,
          label: blendedScore >= 70 ? 'high' : blendedScore >= 30 ? 'medium' : 'low',
          reason: critique.confidenceReason || groundedConfidence.reason
        };

    logger.info('supervisor.stage', { chatId, stage: lastStage, latencyMs: Date.now() - stageStart });

    return {
      success: true,
      output: {
        answer,
        plan,
        evidence,
        sourceCount,
        contradictions,
        confidence,
        docConfidence,
        reviewIssues: critique.issues,
        regenerated: attempts > 0 || evidenceEscalations > 0
      }
    };
  }
}

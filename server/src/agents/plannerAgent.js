import { BaseAgent } from './baseAgent.js';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';

const PLANNER_SYSTEM_PROMPT = `You are the Planner stage of a critical-thinking AI pipeline.
Given a user question, decide HOW to answer it well, before any answer is generated.

Reply with ONLY a JSON object, no other text:
{
  "intent": "<one sentence: what the user actually wants>",
  "taskType": "factual" | "comparison" | "howto" | "opinion" | "code" | "greeting" | "other",
  "category": "biography" | "politics" | "coding" | "algorithms" | "medical" | "legal" | "finance" | "news" | "research" | "document_analysis" | "general",
  "steps": ["step 1", "step 2", ...],
  "needsDocRetrieval": true|false,
  "needsWebSearch": true|false
}

Rules:
- "greeting" or trivial small talk: steps should be minimal (1 step), needsDocRetrieval=false, needsWebSearch=false, category="general".
- "comparison" tasks: steps must cover each thing being compared separately, then a synthesis step.
- category drives which sources are trusted and whether facts get cross-checked — pick the closest match, "general" only when nothing else fits.
- Keep steps to 3-6 items, each a short actionable phrase.`;

// First stage of the critical-thinking pipeline: Question -> Intent Analysis
// -> Task Classification -> reasoning plan -> tool decisions. This is a real
// LLM call (not a heuristic) because intent/task classification needs actual
// language understanding — the cost is accepted per this session's priority
// order (Reasoning > Evidence > Accuracy > Speed).
export class PlannerAgent extends BaseAgent {
  constructor() {
    super('PlannerAgent');
  }

  async run(question, _context = {}) {
    try {
      const res = await fetch(`${OLLAMA_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: OLLAMA_MODEL,
          stream: false,
          options: { temperature: 0.1 },
          messages: [
            { role: 'system', content: PLANNER_SYSTEM_PROMPT },
            { role: 'user', content: question }
          ]
        })
      });
      if (!res.ok) throw new Error(`Planner LLM call failed: ${res.status}`);

      const data = await res.json();
      const raw = data.message?.content || '';
      const plan = parsePlan(raw, question);
      return { success: true, output: plan };
    } catch (err) {
      // Never let planning failure block the whole pipeline — fall back to
      // a generic single-step plan that still triggers retrieval.
      return {
        success: true,
        output: fallbackPlan(question),
        error: err.message
      };
    }
  }
}

const VALID_CATEGORIES = new Set([
  'biography', 'politics', 'coding', 'algorithms', 'medical', 'legal',
  'finance', 'news', 'research', 'document_analysis', 'general'
]);

function parsePlan(raw, question) {
  const match = raw.match(/\{[\s\S]*\}/);
  if (!match) return fallbackPlan(question);
  try {
    const parsed = JSON.parse(match[0]);
    return {
      intent: parsed.intent || question,
      taskType: parsed.taskType || 'other',
      category: VALID_CATEGORIES.has(parsed.category) ? parsed.category : 'general',
      steps: Array.isArray(parsed.steps) && parsed.steps.length > 0 ? parsed.steps : ['Answer the question directly'],
      needsDocRetrieval: parsed.needsDocRetrieval !== false,
      needsWebSearch: parsed.needsWebSearch !== false
    };
  } catch {
    return fallbackPlan(question);
  }
}

function fallbackPlan(question) {
  return {
    intent: question,
    taskType: 'other',
    category: 'general',
    steps: ['Retrieve relevant evidence', 'Reason about the evidence', 'Generate answer'],
    needsDocRetrieval: true,
    needsWebSearch: true
  };
}

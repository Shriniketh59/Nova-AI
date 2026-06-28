import { BaseAgent } from './baseAgent.js';
import { generateWithContinuation } from '../utils/completionGuard.js';

const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';

function buildReasoningPrompt({ question, plan, evidenceSummary, contradictions, memories, feedback }) {
  const contradictionNote = contradictions.length > 0
    ? `\nWarning — these sources disagree, address this explicitly:\n${contradictions.map(c => `- ${c.sourceA} vs ${c.sourceB}`).join('\n')}\n`
    : '';

  const memoryNote = memories.length > 0
    ? `\nRelevant context from earlier in this conversation:\n${memories.join('\n')}\n`
    : '';

  const feedbackNote = feedback
    ? `\nYour previous draft had issues, fix them: ${feedback}\n`
    : '';

  // Greetings/small talk don't need the full report structure — forcing
  // "## Direct Answer" headings onto "hey, how are you" reads absurd and
  // the planner already marks these trivial.
  const structureNote = plan.taskType === 'greeting'
    ? 'Reply naturally in 1-2 sentences, no section headings.'
    : `Structure your answer with these markdown sections, in order:
## Direct Answer
One or two sentences answering the question head-on.
## Detailed Explanation
Full reasoning, addressing every part of a multi-part question.
## Key Findings
A short bullet list of the most important facts from the evidence.
## Conclusion
A closing takeaway sentence.`;

  return `Question: ${question}

Intent: ${plan.intent}
Planned approach: ${plan.steps.join(' -> ')}
${memoryNote}
Evidence gathered:
${evidenceSummary}
${contradictionNote}${feedbackNote}
Think step by step before writing:
1. What do the sources actually say, in relation to the question?
2. Are there patterns or agreement across sources?
3. If this is a comparison, weigh the options explicitly.
4. State your conclusion clearly and directly.

${structureNote}

Write ONLY the final answer text (no "Step 1:" labels, no meta-commentary) — but make sure it reflects real reasoning over the evidence above, not a generic response.`;
}

// Third stage: Evidence Analysis -> Reasoning. Takes the Planner's plan and
// the Research Agent's evidence list and produces a reasoned draft answer —
// "do not jump directly to answers" is enforced by feeding the model an
// explicit step-by-step reasoning scaffold instead of just "answer this".
export class ReasoningAgent extends BaseAgent {
  constructor() {
    super('ReasoningAgent');
  }

  async run(question, context = {}) {
    const { plan = {}, evidenceSummary = '', contradictions = [], memories = [], feedback = null } = context;
    try {
      const prompt = buildReasoningPrompt({ question, plan, evidenceSummary, contradictions, memories, feedback });
      // Structured answers (non-greeting) must come back with every
      // required section and any code block fully closed — auto-continue
      // handles both the token-cap and the open-fence/missing-section cases.
      const answer = await generateWithContinuation(
        [{ role: 'user', content: prompt }],
        { model: OLLAMA_MODEL, numPredict: 4096, temperature: 0.4, requireSections: plan.taskType !== 'greeting' }
      );
      return { success: true, output: { answer } };
    } catch (err) {
      return { success: false, output: { answer: '' }, error: err.message };
    }
  }
}

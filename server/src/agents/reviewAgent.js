import { BaseAgent } from './baseAgent.js';
import { cosineSimilarity } from '../rag.js';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';

const NOT_FOUND_MESSAGE = 'Reliable information was not found in the available sources.';
const CONFLICT_SIMILARITY_THRESHOLD = 0.3; // below this, two on-topic chunks are considered divergent

const CRITIQUE_SYSTEM_PROMPT = `You are the Review stage of a critical-thinking AI pipeline. You did not write this answer — your job is to critique it harshly against the evidence it was supposed to be based on.

Check for:
- Source support: does every claim trace back to the evidence, or is something made up?
- Logic consistency: does the reasoning hold together?
- Missing information: is something important from the evidence left out?
- Hallucination: any specific facts/numbers/names not actually in the evidence?
- Contradictions: does the answer address known source disagreements, or ignore them?
- Completeness: does the answer address every part of the question, not just one piece of a multi-part ask?
- Evidence sufficiency: is the evidence too thin to actually support a confident answer (should more sources be retrieved before answering)?

Reply with ONLY a JSON object:
{
  "pass": true|false,
  "issues": ["issue 1", ...],
  "needsMoreEvidence": true|false,
  "confidenceScore": 0-100,
  "confidenceReason": "<short reason, e.g. '8 sources agree' or '2 sources conflict, no resolution'>"
}`;

// Code domain has no "evidence" to check against — quickValidateCode in
// codeAgent.js already covers syntax/imports/undefined vars statically.
// This LLM pass is for what static analysis can't see: is the algorithm
// actually correct, and does the stated time/space complexity match what
// the code does.
const CODE_CRITIQUE_SYSTEM_PROMPT = `You are the Review stage for a coding answer. The code has already passed static validation (syntax, imports, undefined variables) — your job is to catch what static checks can't:

- Algorithm correctness: does the code actually solve the stated problem, including edge cases it claims to handle?
- Complexity accuracy: does the stated Time/Space Complexity match what the code's loops/recursion/data structures actually do?
- Logic bugs: off-by-one errors, wrong comparison operators, incorrect base cases, mutated-while-iterating bugs.

Reply with ONLY a JSON object:
{
  "pass": true|false,
  "issues": ["issue 1", ...],
  "needsMoreEvidence": false,
  "confidenceScore": 0-100,
  "confidenceReason": "<short reason>"
}`;

// Final decision-making step: Question -> Retrieve -> Validate -> Compare ->
// Generate -> Review -> Return. This agent is the "Review" stage — it
// doesn't call the LLM again (cheap, no added latency on the hot path), it
// validates the answer's grounding using retrieval signal already computed:
// low confidence -> override with the "not found" fallback instead of
// letting a hallucinated-sounding answer through; divergent sources ->
// flag the conflict explicitly rather than silently picking one.
export class ReviewAgent extends BaseAgent {
  constructor() {
    super('ReviewAgent');
  }

  async run(answer, context = {}) {
    const { chunks = [], sources = [], confidence = { score: 0, label: 'low' } } = context;

    if (confidence.label === 'low' || chunks.length === 0) {
      return {
        success: true,
        output: {
          answer: NOT_FOUND_MESSAGE,
          evidence: sources,
          confidence,
          conflict: false
        }
      };
    }

    const conflict = detectConflict(chunks);

    let finalAnswer = answer;
    if (conflict.found) {
      finalAnswer = `${answer}\n\nNote: sources disagree on this point (${conflict.detail}) — treat with caution.`;
    }

    return {
      success: true,
      output: {
        answer: finalAnswer,
        evidence: sources,
        confidence,
        conflict: conflict.found,
        conflictDetail: conflict.found ? conflict.detail : null
      }
    };
  }

  // Real LLM-judge critique for the critical-thinking pipeline (SupervisorAgent).
  // Distinct from run() above (which is the cheap heuristic path ragService.js
  // uses) — this is the "Review every answer" stage from the critical-thinking
  // spec: checks source support / logic / missing info / hallucination /
  // contradictions, and can request regeneration. Accepted latency cost per
  // this session's priority order (Reasoning > Evidence > Accuracy > Speed).
  async critique(answer, { question, evidenceSummary, contradictions = [], domain = 'document' }) {
    const isCode = domain === 'code';
    const userContent = isCode
      ? `Question: ${question}\n\nCode answer to review:\n${answer}`
      : `Question: ${question}\n\nEvidence:\n${evidenceSummary}\n\nKnown source disagreements: ${contradictions.length > 0 ? contradictions.map(c => `${c.sourceA} vs ${c.sourceB}`).join(', ') : 'none'}\n\nAnswer to review:\n${answer}`;

    try {
      const res = await fetch(`${OLLAMA_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: OLLAMA_MODEL,
          stream: false,
          options: { temperature: 0.1 },
          messages: [
            { role: 'system', content: isCode ? CODE_CRITIQUE_SYSTEM_PROMPT : CRITIQUE_SYSTEM_PROMPT },
            { role: 'user', content: userContent }
          ]
        })
      });
      if (!res.ok) throw new Error(`Review LLM call failed: ${res.status}`);

      const data = await res.json();
      const raw = data.message?.content || '';
      return parseCritique(raw);
    } catch (err) {
      // If the critique call itself fails, don't block the pipeline —
      // pass through with a neutral confidence rather than looping forever.
      return { pass: true, issues: [], needsMoreEvidence: false, confidenceScore: 50, confidenceReason: `Review unavailable: ${err.message}` };
    }
  }
}

function parseCritique(raw) {
  const fallback = { pass: true, issues: [], needsMoreEvidence: false, confidenceScore: 50, confidenceReason: 'Could not parse review output' };
  const match = raw.match(/\{[\s\S]*\}/);
  if (!match) return fallback;
  try {
    const parsed = JSON.parse(match[0]);
    return {
      pass: parsed.pass !== false,
      issues: Array.isArray(parsed.issues) ? parsed.issues : [],
      needsMoreEvidence: parsed.needsMoreEvidence === true,
      confidenceScore: typeof parsed.confidenceScore === 'number' ? parsed.confidenceScore : 50,
      confidenceReason: parsed.confidenceReason || ''
    };
  } catch {
    return fallback;
  }
}

// Heuristic: two chunks from different files that both scored above the
// retrieval threshold for the same query, but whose embeddings are far apart,
// are "on-topic but divergent" — a proxy for conflicting information without
// a second LLM call to actually read and compare claims.
function detectConflict(chunks) {
  const distinctFileChunks = [];
  const seenFiles = new Set();
  for (const c of chunks) {
    if (!c.embedding || seenFiles.has(c.original_filename)) continue;
    seenFiles.add(c.original_filename);
    distinctFileChunks.push(c);
  }

  for (let i = 0; i < distinctFileChunks.length; i++) {
    for (let j = i + 1; j < distinctFileChunks.length; j++) {
      const sim = cosineSimilarity(distinctFileChunks[i].embedding, distinctFileChunks[j].embedding);
      if (sim < CONFLICT_SIMILARITY_THRESHOLD) {
        return {
          found: true,
          detail: `${distinctFileChunks[i].original_filename} vs ${distinctFileChunks[j].original_filename}`
        };
      }
    }
  }
  return { found: false, detail: null };
}

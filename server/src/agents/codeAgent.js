import { BaseAgent } from './baseAgent.js';
import { isTruncated, closeUnbalancedFences } from '../utils/completionGuard.js';
import { quickValidateCode } from '../utils/codeValidation.js';
import { ReviewAgent } from './reviewAgent.js';

// Off by default — static validation (quickValidateCode) catches syntax/
// import/undefined-var issues for free. This adds an LLM critique pass for
// algorithm-correctness/complexity-accuracy bugs static checks can't see,
// at the cost of one extra Ollama round-trip toward the 3-8s coding target.
// Enable once latency budget allows: CODE_LLM_REVIEW=true.
const ENABLE_CODE_LLM_REVIEW = process.env.CODE_LLM_REVIEW === 'true';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
// Prefer a coding-tuned model when one is installed (Qwen2.5-Coder /
// DeepSeek-Coder / CodeLlama all speak Ollama's API identically) — falls
// back to the general chat model if it isn't pulled, so this never breaks
// a fresh install that only has llama3.2.
const CODE_MODEL = process.env.OLLAMA_CODE_MODEL || process.env.OLLAMA_MODEL || 'llama3.2:3b';
const CODE_NUM_PREDICT = parseInt(process.env.CODE_NUM_PREDICT || '2048', 10);
const MAX_CONTINUATIONS = parseInt(process.env.MAX_CONTINUATIONS || '3', 10);
const MAX_REGENERATIONS = 1; // bounds the fix->still-broken->regenerate loop

const REQUIRED_SECTIONS = [
  'Problem Understanding', 'Key Concepts', 'Approach', 'Algorithm', 'Code',
  'Complexity Analysis', 'Edge Cases', 'Example Execution', 'Conclusion', 'Confidence Score'
];

const DSA_RE = /\b(leetcode|dsa|hackerrank|codeforces|two sum|merge sort|quick sort|binary search|fibonacci|dynamic programming|graph traversal|knapsack|sliding window)\b/i;

// Broad build/design requests ("build a todo app", "create an e-commerce
// platform") need a plan before code, not a single code block — a request
// this open-ended can't be answered correctly in one pass, so skip the code
// pipeline entirely and ask what to build first.
const BROAD_BUILD_RE = /\b(build|create|design|develop|make)\b(?:(?!\b(?:function|method|class|component|endpoint|query|regex|script|snippet)\b)[\s\S]){0,40}\b(app|application|system|platform|website|web ?app|service|api|dashboard|game|bot|chatbot|tool)\b/i;

const CODE_SYSTEM_PROMPT = `You are Nova AI's elite coding assistant — answer at the quality of a senior software architect and competitive programmer. Never generate incomplete, uncompilable, or low-quality code. Never write a generic or filler explanation — every sentence must say something specific to this exact problem.

Workflow before writing anything: understand the problem fully (input/output/constraints/edge cases), identify the concepts/data structures involved, design the algorithm, then write complete code, then check it, then derive real complexity from the code you actually wrote.

Structure every answer with these exact markdown sections, in order, every time — never skip one:
# Problem Understanding
Restate the problem precisely: input, output, constraints, edge cases to handle.
# Key Concepts
The specific data structures, algorithms, or language features this problem requires, and why each is needed.
# Approach
The reasoning behind the chosen method — what alternatives were considered and why this one wins.
# Algorithm
Numbered steps.
# Code
One fenced code block, correct language tag, complete and runnable — every brace closed, every function returns what its signature promises, no missing imports.
# Complexity Analysis
Time Complexity: derived from the actual loops/recursion in the code above — never guessed. If genuinely uncertain (e.g. depends on input distribution), say so explicitly and state the assumption.
Space Complexity: same — derived from the actual data structures used.
Worst Case: the specific input shape that triggers it.
Average Case: only if it meaningfully differs from worst case.
# Edge Cases
List the concrete edge cases this code handles (empty input, single element, duplicates, overflow, etc.) — not generic boilerplate.
# Example Execution
A concrete input run through the code with the actual output.
# Conclusion
One paragraph: summarize the solution and its real tradeoffs (when you'd pick a different approach).
# Confidence Score
A percentage with one line on why (validated vs assumptions made).

Never return code only — every section above is mandatory.`;

const LEETCODE_SYSTEM_PROMPT = `${CODE_SYSTEM_PROMPT}

This is a DSA/competitive-programming question. In the # Code section, provide BOTH:
1. Brute Force Solution — correct but naive.
2. Optimized Solution — the efficient approach.
Then in Complexity Analysis, compare both and explain concretely why the optimized solution is better (what work it avoids).`;

const PLAN_SYSTEM_PROMPT = `You are Nova AI's planning assistant for broad build/design requests. The user asked to build something too large for a single code answer — scope it first, don't write code yet.

Reply with ONLY this markdown structure:
# Implementation Plan
## Phase 1: <name>
<1-2 sentences>
## Phase 2: <name>
<1-2 sentences>
## Phase 3: <name>
<1-2 sentences>
# Estimated Files
A bullet list of the files/modules this would need.
# Estimated Components
A bullet list of the major components/classes/services.
# Estimated APIs
A bullet list of the endpoints or interfaces needed (omit this section if not applicable).

End with exactly this line, verbatim:
Want me to generate the code for this plan?`;

function buildFixPrompt(answer, issues) {
  return `Your previous answer has these specific defects:\n${issues.map(i => `- ${i}`).join('\n')}\n\nHere is your previous answer:\n${answer}\n\nReturn the FULL corrected answer (all sections, same structure), fixing only these defects. Do not add commentary about the fix.`;
}

function buildRegeneratePrompt(question, issues) {
  return `${question}\n\nA previous attempt at this had unresolved defects after one fix pass: ${issues.join('; ')}. Write a fresh, careful answer that avoids these specific mistakes.`;
}

function missingSections(text) {
  return REQUIRED_SECTIONS.filter(s => !text.includes(s));
}

function confidenceFromValidation(validation, regenerated) {
  if (validation.pass && !regenerated) {
    return { score: 97, label: 'high', reason: 'Code reviewed and passed all validation checks (syntax, imports, returns, complexity).' };
  }
  if (validation.pass && regenerated) {
    return { score: 88, label: 'high', reason: 'Code passed validation after one regeneration pass — minor assumptions possible.' };
  }
  return { score: 65, label: 'medium', reason: `Validation still flags: ${validation.issues.join('; ')} — review before using in production.` };
}

// Coding fast path: Question -> Code Agent -> Quick Validation -> Response.
// Deliberately bypasses Research/Planner/Review — none of those add
// accuracy for "write a mergesort", they only add the 1-3min critical-
// thinking pipeline's latency for zero benefit on a self-contained ask.
export class CodeAgent extends BaseAgent {
  constructor() {
    super('CodeAgent');
    this.reviewAgent = new ReviewAgent();
  }

  async run(question) {
    const { answer, validation, confidence } = await this.runStream(question, () => {});
    return { success: true, output: { answer, validation, confidence } };
  }

  // Streams tokens to `onToken` as they arrive (so the UI shows code while
  // it's still generating), then runs quick validation, fixes concrete
  // defects, and — if still broken after the fix — regenerates from
  // scratch once with the defects named explicitly. "Never return buggy
  // code" is enforced by this chain, not by hoping the first pass is clean.
  async runStream(question, onToken) {
    if (BROAD_BUILD_RE.test(question)) {
      const { answer: plan } = await this._generateOnce(PLAN_SYSTEM_PROMPT, question, onToken);
      return {
        answer: plan,
        validation: { pass: true, issues: [] },
        confidence: { score: 90, label: 'high', reason: 'Implementation plan only — no code generated yet.' }
      };
    }

    const systemPrompt = DSA_RE.test(question) ? LEETCODE_SYSTEM_PROMPT : CODE_SYSTEM_PROMPT;
    let regenerated = false;

    const { answer: firstPass } = await this._generateOnce(systemPrompt, question, onToken);
    let answer = firstPass;
    let validation = this._validate(answer);

    if (!validation.pass) {
      const fixed = await this._fix(systemPrompt, answer, validation.issues);
      if (fixed) {
        answer = fixed;
        validation = this._validate(answer);
      }
    }

    if (!validation.pass && validation.codeBroken) {
      // Only regenerate from scratch for an actual code defect (syntax,
      // missing imports, etc) — a missing markdown header after one fix
      // pass isn't worth a third full LLM round-trip on a small model.
      regenerated = true;
      const { answer: retryAnswer } = await this._generateOnce(
        systemPrompt, buildRegeneratePrompt(question, validation.issues), () => {}
      );
      answer = retryAnswer;
      validation = this._validate(answer);
    }

    let confidence = confidenceFromValidation(validation, regenerated);

    if (ENABLE_CODE_LLM_REVIEW && validation.pass) {
      const codeCritique = await this.reviewAgent.critique(answer, { question, domain: 'code' });
      if (!codeCritique.pass) {
        validation = { ...validation, pass: false, issues: [...validation.issues, ...codeCritique.issues] };
        confidence = { score: Math.min(confidence.score, codeCritique.confidenceScore), label: codeCritique.confidenceScore >= 70 ? 'high' : codeCritique.confidenceScore >= 30 ? 'medium' : 'low', reason: codeCritique.confidenceReason || 'LLM review flagged algorithm/complexity issues.' };
      }
    }

    return { answer, validation, confidence };
  }

  _validate(answer) {
    const codeIssues = quickValidateCode(answer);
    const sectionIssues = missingSections(answer);
    return {
      pass: codeIssues.pass && sectionIssues.length === 0,
      codeBroken: !codeIssues.pass,
      issues: [...codeIssues.issues, ...sectionIssues.map(s => `Missing required section: ${s}`)]
    };
  }

  async _generateOnce(systemPrompt, userContent, onToken) {
    let convo = [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userContent }
    ];
    let answer = '';

    for (let round = 0; round <= MAX_CONTINUATIONS; round++) {
      let piece = '';
      let doneReason = 'stop';

      const res = await fetch(`${OLLAMA_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: CODE_MODEL,
          stream: true,
          messages: convo,
          options: { temperature: 0.2, top_p: 0.9, num_predict: CODE_NUM_PREDICT }
        })
      });
      if (!res.ok || !res.body) throw new Error(`Code generation failed: ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          const chunk = JSON.parse(line);
          const token = chunk.message?.content || '';
          if (token) {
            piece += token;
            answer += token;
            onToken(token);
          }
          if (chunk.done) doneReason = chunk.done_reason || 'stop';
        }
      }

      if (!isTruncated(answer, doneReason)) break;
      convo = [
        ...convo,
        { role: 'assistant', content: piece },
        { role: 'user', content: 'Continue exactly where you left off. Do not repeat anything already written.' }
      ];
    }

    return { answer: closeUnbalancedFences(answer) };
  }

  async _fix(systemPrompt, answer, issues) {
    const res = await fetch(`${OLLAMA_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: CODE_MODEL,
        stream: false,
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: buildFixPrompt(answer, issues) }
        ],
        options: { temperature: 0.2, top_p: 0.9, num_predict: CODE_NUM_PREDICT }
      })
    });
    if (!res.ok) return null;
    const data = await res.json();
    const fixed = data.message?.content || '';
    return fixed ? closeUnbalancedFences(fixed) : null;
  }
}

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const MAX_CONTINUATIONS = parseInt(process.env.MAX_CONTINUATIONS || '3', 10);

const REQUIRED_SECTIONS = ['Direct Answer', 'Detailed Explanation', 'Key Findings', 'Conclusion'];

// Ollama sets done_reason="length" when generation was cut off by
// num_predict — the authoritative truncation signal. Also catch
// generations that stopped "cleanly" but left a code fence open, or
// (for structured answers) are missing a required section heading —
// those still render broken even though the model thinks it's done.
export function isTruncated(text, doneReason, { requireSections = false } = {}) {
  if (doneReason === 'length') return true;
  if ((text.match(/```/g) || []).length % 2 !== 0) return true;
  if (requireSections && REQUIRED_SECTIONS.some(s => !text.includes(s))) return true;
  return false;
}

export function closeUnbalancedFences(text) {
  const fenceCount = (text.match(/```/g) || []).length;
  return fenceCount % 2 !== 0 ? `${text.trimEnd()}\n\`\`\`` : text;
}

// Auto-continue: if the model hit the token cap, left a code block open, or
// skipped a required section, ask it to pick up exactly where it left off
// instead of returning a truncated answer. Bounded by MAX_CONTINUATIONS so
// a model that never emits a clean stop can't loop forever.
export async function generateWithContinuation(messages, { model, numPredict = 1500, temperature = 0.4, requireSections = false } = {}) {
  let answer = '';
  let convo = [...messages];

  for (let round = 0; round <= MAX_CONTINUATIONS; round++) {
    const res = await fetch(`${OLLAMA_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        stream: false,
        options: { temperature, num_predict: numPredict },
        messages: convo
      })
    });
    if (!res.ok) throw new Error(`Generation call failed: ${res.status}`);

    const data = await res.json();
    const piece = data.message?.content || '';
    answer += piece;
    const doneReason = data.done_reason || 'stop';

    if (!isTruncated(answer, doneReason, { requireSections })) {
      return answer;
    }

    convo = [
      ...convo,
      { role: 'assistant', content: piece },
      { role: 'user', content: 'Continue exactly where you left off. Do not repeat anything already written, do not restart the answer.' }
    ];
  }

  return closeUnbalancedFences(answer);
}

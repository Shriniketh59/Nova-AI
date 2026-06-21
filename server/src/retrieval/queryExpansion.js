const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';
const EXPANSION_TIMEOUT_MS = 4000;

// Asks the LLM for 2 alternate phrasings/sub-questions of the user query, so
// retrieval also runs against wording the user didn't use (catches chunks
// that would be missed by lexical/embedding match on the literal phrasing).
// Bounded by a short timeout with empty-array fallback — expansion is a
// recall booster, never allowed to block or fail the main retrieval path.
export async function expandQuery(query) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), EXPANSION_TIMEOUT_MS);

  try {
    const res = await fetch(`${OLLAMA_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({
        model: OLLAMA_MODEL,
        stream: false,
        options: { temperature: 0.3, num_predict: 100 },
        messages: [{
          role: 'user',
          content: `Rewrite this question as 2 alternate phrasings that preserve its meaning, for search recall. Reply with ONLY a JSON array of 2 strings, nothing else.\n\nQuestion: ${query}`
        }]
      })
    });
    if (!res.ok) return [];

    const data = await res.json();
    const raw = data.message?.content || '';
    const match = raw.match(/\[[\s\S]*\]/);
    if (!match) return [];

    const parsed = JSON.parse(match[0]);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(s => typeof s === 'string' && s.trim()).slice(0, 2);
  } catch {
    return [];
  } finally {
    clearTimeout(timeoutId);
  }
}

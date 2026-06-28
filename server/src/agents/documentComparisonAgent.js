import { BaseAgent } from './baseAgent.js';
import { generateWithContinuation } from '../utils/completionGuard.js';

const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';
const MAX_DOC_CHARS = 4000; // per document, to keep both docs + prompt within a small model's context window

const SYSTEM_PROMPT = `You are Nova AI's Document Comparison Agent. You are given two documents and must compare them directly — never substitute outside knowledge for either document's actual content.

Reply with this exact markdown structure:
## Agreements
Bullet list of points both documents state consistently.
## Differences
Bullet list of points where the documents disagree or one states something the other doesn't, naming which document says what.
## Summary
One paragraph: the overall relationship between the two documents (e.g. one supersedes the other, they cover different scope, they conflict on a key point).`;

// Document-grounded comparison (the "compare these documents" request
// documentAnalysisAgent.js doesn't handle — that agent analyzes ONE
// document's content, this one diffs TWO). Bypasses web search for the
// same reason: Uploaded Document > Web Search whenever a file is attached.
export class DocumentComparisonAgent extends BaseAgent {
  constructor() {
    super('DocumentComparisonAgent');
  }

  async run(query, context = {}) {
    const { documents = [] } = context; // [{ fileName, text }, ...]
    if (documents.length < 2) {
      return { success: true, output: { answer: 'Comparison needs at least two uploaded documents in this chat — only one was found.' } };
    }

    const [docA, docB] = documents.slice(-2);
    const truncate = (text) => text.length > MAX_DOC_CHARS ? `${text.slice(0, MAX_DOC_CHARS)}\n[...truncated]` : text;

    const prompt = `Document A (${docA.fileName}):\n${truncate(docA.text)}\n\nDocument B (${docB.fileName}):\n${truncate(docB.text)}\n\nRequest: ${query}`;

    try {
      const answer = await generateWithContinuation(
        [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: prompt }
        ],
        { model: OLLAMA_MODEL, numPredict: 1500, temperature: 0.3 }
      );
      return { success: true, output: { answer, comparedFiles: [docA.fileName, docB.fileName] } };
    } catch (err) {
      return { success: false, output: { answer: '' }, error: err.message };
    }
  }
}

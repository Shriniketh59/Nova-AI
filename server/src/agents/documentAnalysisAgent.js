import { BaseAgent } from './baseAgent.js';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';

const SYSTEM_PROMPT = `You are Nova AI's Document Analysis Agent.
Analyze ONLY the document content provided below. Never reference external websites, tools, or generic advice not grounded in this document.
If the document doesn't contain enough information to answer, say so explicitly — never fabricate or substitute web knowledge.`;

// Document-grounded analysis (review/summarize/evaluate an uploaded file).
// Deliberately bypasses web search entirely — per Task Router, an attached
// file means Uploaded Document is the only allowed source for this turn.
export class DocumentAnalysisAgent extends BaseAgent {
  constructor() {
    super('DocumentAnalysisAgent');
  }

  async run(query, context = {}) {
    const { documentText = '', fileName = 'document' } = context;
    if (!documentText.trim()) {
      return { success: true, output: { answer: `Could not extract any text from ${fileName}.` } };
    }

    try {
      const res = await fetch(`${OLLAMA_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: OLLAMA_MODEL,
          stream: false,
          options: { temperature: 0.3, num_predict: 1200 },
          messages: [
            { role: 'system', content: SYSTEM_PROMPT },
            { role: 'user', content: `Document (${fileName}):\n${documentText}\n\nRequest: ${query}` }
          ]
        })
      });
      if (!res.ok) throw new Error(`Document analysis LLM call failed: ${res.status}`);

      const data = await res.json();
      return { success: true, output: { answer: data.message?.content || '' } };
    } catch (err) {
      return { success: false, output: { answer: '' }, error: err.message };
    }
  }
}

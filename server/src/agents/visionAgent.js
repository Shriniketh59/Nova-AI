import fs from 'fs';
import { BaseAgent } from './baseAgent.js';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_VISION_MODEL = process.env.OLLAMA_VISION_MODEL || 'llava';

const SYSTEM_PROMPT = `You are Nova AI's Vision Agent. Analyze ONLY the attached image —
extract any visible text (OCR), describe charts/tables/screenshots/documents shown,
and answer the user's request grounded strictly in what is visible. Never search
external websites or substitute outside knowledge for what the image actually shows.`;

// Highest-priority route: an attached image always wins over document/RAG/web
// search (see taskRouter.js priority order). Uses Ollama's multimodal chat
// endpoint (image bytes as base64 in the `images` field) — same /api/chat
// shape as documentAnalysisAgent.js, just with an image attached.
export class VisionAgent extends BaseAgent {
  constructor() {
    super('VisionAgent');
  }

  async run(query, context = {}) {
    const { filePath, fileName = 'image' } = context;
    if (!filePath || !fs.existsSync(filePath)) {
      return { success: false, output: { answer: `Could not read image ${fileName}.` }, error: 'file_missing' };
    }

    try {
      const imageBase64 = fs.readFileSync(filePath).toString('base64');
      const res = await fetch(`${OLLAMA_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: OLLAMA_VISION_MODEL,
          stream: false,
          options: { temperature: 0.2, num_predict: 1200 },
          messages: [
            { role: 'system', content: SYSTEM_PROMPT },
            { role: 'user', content: query || 'Describe and analyze this image.', images: [imageBase64] }
          ]
        })
      });
      if (!res.ok) throw new Error(`Vision LLM call failed: ${res.status}`);

      const data = await res.json();
      return { success: true, output: { answer: data.message?.content || '' } };
    } catch (err) {
      return { success: false, output: { answer: `Vision analysis failed: ${err.message}` }, error: err.message };
    }
  }
}

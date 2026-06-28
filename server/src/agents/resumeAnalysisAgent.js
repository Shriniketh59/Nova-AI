import { BaseAgent } from './baseAgent.js';
import { calculateAtsScore } from '../services/atsService.js';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';

const SYSTEM_PROMPT = `You are Nova AI's Resume Analysis Agent.
Analyze ONLY the resume text provided. Never reference external websites, resume builders, or ATS checker tools — you are the analysis, not a referral to one.
Structure your response with these exact headings: Skills Analysis, Project Analysis, Resume Improvements.`;

// "Review my resume" — combines real extraction (skills/sections, same
// parser ATS scoring uses) with a grounded LLM qualitative pass. Web search
// is never invoked here; Task Router only routes here when a resume file
// is attached, so the resume text IS the source of truth.
export class ResumeAnalysisAgent extends BaseAgent {
  constructor() {
    super('ResumeAnalysisAgent');
  }

  async run(query, context = {}) {
    const { documentText = '', fileName = 'resume' } = context;
    if (!documentText.trim()) {
      return { success: true, output: { answer: `Could not extract any text from ${fileName}.` } };
    }

    const extraction = calculateAtsScore(documentText);

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
            {
              role: 'user',
              content: `Resume (${fileName}):\n${documentText}\n\nExtracted skills: ${extraction.skillsFound.join(', ') || 'none detected'}\nSections detected: ${Object.entries(extraction.sectionsDetected).filter(([, v]) => v).map(([k]) => k).join(', ') || 'none'}\n\nRequest: ${query}`
            }
          ]
        })
      });
      if (!res.ok) throw new Error(`Resume analysis LLM call failed: ${res.status}`);

      const data = await res.json();
      const answer = data.message?.content || '';
      return { success: true, output: { answer, atsScore: extraction.score, skillsFound: extraction.skillsFound } };
    } catch (err) {
      return { success: false, output: { answer: '' }, error: err.message };
    }
  }
}

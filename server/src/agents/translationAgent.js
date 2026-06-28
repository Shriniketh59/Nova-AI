import { BaseAgent } from './baseAgent.js';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || 'llama3.2:3b';

const SUPPORTED_LANGUAGES = [
  'English', 'Tamil', 'Telugu', 'Kannada', 'Malayalam', 'Hindi', 'Bengali',
  'Marathi', 'Gujarati', 'Punjabi', 'Urdu', 'Arabic', 'French', 'German',
  'Spanish', 'Japanese', 'Korean', 'Chinese', 'Russian', 'Portuguese'
];

const SYSTEM_PROMPT = `You are Nova AI Multilingual Translation Engine.

Your only task is accurate translation between languages.

Supported Languages: ${SUPPORTED_LANGUAGES.join(', ')}.

Instructions:
1. Automatically detect the source language.
2. Translate into the requested target language.
3. Preserve: Meaning, Context, Tone, Names, Numbers, Dates, Technical terms.
4. Never: Summarize, Explain, Add information, Remove information, Answer the content.
5. If the input is a word, return the translated word only. If a sentence, return the translated sentence only. If a paragraph, return the translated paragraph only.
6. Maintain original formatting.
7. For programming content: keep code unchanged, translate comments only if requested.
8. If translation is ambiguous, choose the most natural and commonly used translation.

Output Format (exactly, no extra text):
Detected Language: <language>

Translation: <translated text>`;

function buildUserMessage(targetLanguage, text) {
  return `Translate to ${targetLanguage}:\n${text}`;
}

// Parses the model's "Detected Language: X\n\nTranslation: Y" output into
// structured fields, so API consumers don't have to regex the raw text.
function parseTranslationOutput(raw) {
  const detectedMatch = raw.match(/Detected Language:\s*(.+)/i);
  const translationMatch = raw.match(/Translation:\s*([\s\S]*)/i);

  if (translationMatch) {
    return {
      detectedLanguage: detectedMatch ? detectedMatch[1].trim() : null,
      translation: translationMatch[1].trim()
    };
  }

  // Model sometimes skips the "Translation:" label — fall back to everything
  // after the detected-language line instead of dumping the whole raw block.
  if (detectedMatch) {
    const afterDetected = raw.slice(raw.indexOf(detectedMatch[0]) + detectedMatch[0].length).trim();
    return { detectedLanguage: detectedMatch[1].trim(), translation: afterDetected };
  }

  return { detectedLanguage: null, translation: raw.trim() };
}

export class TranslationAgent extends BaseAgent {
  constructor() {
    super('TranslationAgent');
  }

  /**
   * @param {string} text - word, sentence, or paragraph to translate
   * @param {{ targetLanguage: string }} context
   */
  async run(text, context = {}) {
    const { targetLanguage } = context;
    if (!targetLanguage || !SUPPORTED_LANGUAGES.includes(targetLanguage)) {
      return {
        success: false,
        output: null,
        error: `targetLanguage must be one of: ${SUPPORTED_LANGUAGES.join(', ')}`
      };
    }

    try {
      const res = await fetch(`${OLLAMA_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: OLLAMA_MODEL,
          messages: [
            { role: 'system', content: SYSTEM_PROMPT },
            { role: 'user', content: buildUserMessage(targetLanguage, text) }
          ],
          stream: false,
          options: { temperature: 0.1, num_predict: 512 }
        })
      });

      if (!res.ok) {
        throw new Error(`LLM request failed with status ${res.status}`);
      }

      const data = await res.json();
      const raw = data.message?.content || '';
      const { detectedLanguage, translation } = parseTranslationOutput(raw);

      return { success: true, output: { detectedLanguage, translation, targetLanguage } };
    } catch (err) {
      return { success: false, output: null, error: err.message };
    }
  }
}

export { SUPPORTED_LANGUAGES };

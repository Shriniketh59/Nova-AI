import { BaseAgent } from './baseAgent.js';
import { runRagQuery } from '../services/ragService.js';

// Real wrapper: routes to the existing single-source RAG pipeline. Once
// retrievalService.js grows hybrid/rerank/multi-collection support, this
// agent is the only place that needs to start calling it directly instead
// of going through ragService.js.
export class KnowledgeAgent extends BaseAgent {
  constructor() {
    super('KnowledgeAgent');
  }

  async run(task, context = {}) {
    try {
      const { answer, sources } = await runRagQuery(task, context.chatId, context.options);
      return { success: true, output: { answer, sources } };
    } catch (err) {
      return { success: false, output: null, error: err.message };
    }
  }
}

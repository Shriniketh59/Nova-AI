import { BaseAgent } from './baseAgent.js';
import { runRagQuery } from '../services/ragService.js';

// Wraps the existing RAG pipeline behind the agent contract so a future
// PlannerAgent can dispatch "look this up in the docs" sub-tasks to it.
export class RagAgent extends BaseAgent {
  constructor() {
    super('RagAgent');
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

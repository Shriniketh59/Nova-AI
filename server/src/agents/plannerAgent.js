import { BaseAgent } from './baseAgent.js';

// Future home of multi-step task decomposition: breaks a user request into
// sub-tasks and routes each to the right specialist agent (RagAgent,
// CodeAgent, ReviewAgent). Not wired into any route yet — single-step
// RAG queries go straight through ragService.js until this is built out.
export class PlannerAgent extends BaseAgent {
  constructor(agents = {}) {
    super('PlannerAgent');
    this.agents = agents; // e.g. { rag: RagAgent, code: CodeAgent, review: ReviewAgent }
  }

  async run(_task, _context) {
    throw new Error('PlannerAgent.run() not implemented yet — single-agent RAG flow only');
  }
}

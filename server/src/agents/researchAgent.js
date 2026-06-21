import { BaseAgent } from './baseAgent.js';

// Target design: takes a question that spans multiple sources/collections,
// runs KnowledgeAgent (and eventually WebIngestor-backed search) across each,
// then asks the LLM to synthesize one coherent narrative citing all of them —
// distinct from KnowledgeAgent's single-pass "answer from these chunks".
export class ResearchAgent extends BaseAgent {
  constructor() {
    super('ResearchAgent');
  }

  async run(_task, _context) {
    throw new Error('ResearchAgent.run() not implemented yet — needs multi-source fan-out + synthesis prompt');
  }
}

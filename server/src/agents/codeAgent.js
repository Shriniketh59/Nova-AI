import { BaseAgent } from './baseAgent.js';

// Placeholder for a future code-generation specialist (e.g. for an in-chat
// "write me a function" flow). Not implemented or wired in yet.
export class CodeAgent extends BaseAgent {
  constructor() {
    super('CodeAgent');
  }

  async run(_task, _context) {
    throw new Error('CodeAgent.run() not implemented yet');
  }
}

import { BaseAgent } from './baseAgent.js';
import { KnowledgeAgent } from './knowledgeAgent.js';

// Target design: classify user intent (doc question / code task / research
// task / general chat), route to the matching agent(s), run ReviewAgent on
// the result before returning. Currently routes everything to KnowledgeAgent
// as the only fully-wired agent — real routing logic (intent classification
// + multi-agent fan-out) is the next milestone, not a stub placeholder,
// since "always use KnowledgeAgent" is a valid (if limited) default policy.
export class SupervisorAgent extends BaseAgent {
  constructor(agents = {}) {
    super('SupervisorAgent');
    this.agents = {
      knowledge: agents.knowledge || new KnowledgeAgent(),
      ...agents
    };
  }

  async run(task, context = {}) {
    // TODO: real intent classification. For now: every request is a
    // knowledge/RAG request, since that's the only production-ready agent.
    const result = await this.agents.knowledge.run(task, context);

    // TODO: pass result through ReviewAgent once it's implemented:
    // const reviewed = await this.agents.review.run(result, context);

    return result;
  }
}

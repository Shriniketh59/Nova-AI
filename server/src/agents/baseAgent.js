// Shared contract for all agents. Each agent takes a task description + shared
// context and returns a structured result the orchestrator (future PlannerAgent)
// can chain into the next step.
export class BaseAgent {
  constructor(name) {
    if (this.constructor === BaseAgent) {
      throw new Error('BaseAgent is abstract and cannot be instantiated directly');
    }
    this.name = name;
  }

  // Override in subclasses. Must return { success, output, error? }.
  async run(_task, _context) {
    throw new Error(`${this.name}.run() not implemented`);
  }
}

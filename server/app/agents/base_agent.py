class BaseAgent:
    """Shared contract for all agents. Each agent takes a task description +
    shared context and returns a structured result the orchestrator can chain
    into the next step."""

    def __init__(self, name: str):
        if type(self) is BaseAgent:
            raise TypeError("BaseAgent is abstract and cannot be instantiated directly")
        self.name = name

    async def run(self, task, context: dict | None = None) -> dict:
        raise NotImplementedError(f"{self.name}.run() not implemented")

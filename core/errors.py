"""Error types for orchestration and agent failures."""


class SwarmError(Exception):
    """Base error for the ai_swarm platform."""


class GraphError(SwarmError):
    """Error in graph definition or traversal."""


class NodeError(SwarmError):
    """Error during node execution."""

    def __init__(self, node_id: str, message: str):
        self.node_id = node_id
        super().__init__(f"Node '{node_id}': {message}")


class AgentValidationError(NodeError):
    """Agent output failed schema or business validation."""

    def __init__(self, node_id: str, agent_id: str, message: str):
        self.agent_id = agent_id
        super().__init__(node_id, f"agent '{agent_id}' validation failed: {message}")


class BudgetExceededError(SwarmError):
    """A budget cap has been reached."""

    def __init__(self, scope: str, limit: float, current: float):
        self.scope = scope
        self.limit = limit
        self.current = current
        super().__init__(f"Budget exceeded for {scope}: {current:.2f} >= {limit:.2f}")


class MissingStateError(NodeError):
    """Required state keys are missing before node execution."""

    def __init__(self, node_id: str, missing_keys: list[str]):
        self.missing_keys = missing_keys
        super().__init__(node_id, f"missing state keys: {missing_keys}")


class ModelAPIError(SwarmError):
    """Model API call failed (timeout, rate limit, connection error)."""

    def __init__(self, model: str, message: str, retryable: bool = True):
        self.model = model
        self.retryable = retryable
        super().__init__(f"Model '{model}': {message}")

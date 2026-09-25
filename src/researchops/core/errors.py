"""Agent system errors."""


class ResearchOpsError(Exception):
    """Base error for the agent platform."""


class ToolError(ResearchOpsError):
    """A tool execution failed; the observation is fed back to the agent."""


class PolicyViolation(ResearchOpsError):
    """A tool call was denied by the guardrail policy engine."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class ApprovalRequired(ResearchOpsError):
    """Raised by the tool gateway when an action needs human approval."""

    def __init__(self, action: str, detail: dict, risk: str, signature: str,
                 estimated_cost_usd: float = 0.0, estimated_minutes: float = 0.0):
        self.action = action
        self.detail = detail
        self.risk = risk
        self.signature = signature
        self.estimated_cost_usd = estimated_cost_usd
        self.estimated_minutes = estimated_minutes
        super().__init__(f"approval required for {action} (risk={risk})")


class BudgetExceeded(ResearchOpsError):
    """Run exceeded its cost / time / tool-call budget."""


class SandboxError(ResearchOpsError):
    """The sandbox could not execute a job."""


class LLMSchemaError(ResearchOpsError):
    """The LLM returned output that failed schema validation."""

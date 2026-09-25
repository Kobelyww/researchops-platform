"""Declarative policy engine: who may call what, and what requires approval."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.types import RiskLevel


@dataclass
class Decision:
    allowed: bool
    needs_approval: bool
    reason: str


class PolicyEngine:
    """Agent-role policy for tool calls.

    Rules:
    - Unknown tools are denied (allowlist model).
    - LOW risk: automatic.
    - MEDIUM/HIGH risk: require human approval unless the operator pre-approved
      at task creation (auto_approve) — HIGH additionally requires
      allow_high_risk_auto, so headless mode cannot silently push to GitHub.
    """

    def __init__(self, auto_approve: bool = False, allow_high_risk_auto: bool = False):
        self.auto_approve = auto_approve
        self.allow_high_risk_auto = allow_high_risk_auto

    def evaluate(self, tool_name: str, risk: RiskLevel, granted: bool, rejected: bool) -> Decision:
        if rejected:
            return Decision(False, False, "operator rejected this action")
        if granted:
            return Decision(True, False, "previously approved for this run")
        if risk is RiskLevel.LOW:
            return Decision(True, False, "low risk: automatic")
        if self.auto_approve and (risk is RiskLevel.MEDIUM or (risk is RiskLevel.HIGH and self.allow_high_risk_auto)):
            return Decision(True, False, f"operator pre-approved {risk.value}-risk actions")
        return Decision(False, True, f"{risk.value}-risk action requires human approval")

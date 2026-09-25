"""Per-run metrics aggregation: tool calls, retries, tokens, cost, latency."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunMetrics:
    tool_calls: int = 0
    failed_calls: int = 0
    retries: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    approvals_requested: int = 0
    approvals_granted: int = 0
    repairs: int = 0
    extra: dict = field(default_factory=dict)

    def add_usage(self, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        self.llm_calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost_usd

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["cost_usd"] = round(self.cost_usd, 6)
        d["latency_s"] = round(self.latency_s, 2)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> RunMetrics:
        m = cls()
        for k, v in (d or {}).items():
            if hasattr(m, k):
                setattr(m, k, v)
        return m

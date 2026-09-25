"""Deterministic graders for ResearchOpsBench.

Each grade() returns per-metric scores; benchmark.py aggregates them into the
headline table. LLM-judge grading is pluggable but off by default so CI stays
deterministic and free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CaseResult:
    case_id: str
    success: bool
    tool_selection: float  # jaccard(used, expected)
    tool_execution_success: float  # ok tool calls / total
    citation_precision: float  # verified citations / total
    groundedness: float
    recovery: float  # 1.0 if repairs led to success, 0 if exhausted
    hallucination_penalty: float  # fraction of unverified citations
    latency_s: float
    cost_usd: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def load_dataset(path: Path | None = None) -> list[dict[str, Any]]:
    p = Path(path or Path(__file__).parent / "dataset" / "tasks.jsonl")
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def grade(case: dict[str, Any], run_result: dict[str, Any]) -> CaseResult:
    """run_result shape mirrors the persisted RunRow + trace:
    {status, report_md, metrics:{tool_calls, failed_calls, repairs, ...},
     tool_calls:[{tool, status}], citations:[{url, verified}], plan:[...]}
    """
    grader = case.get("grader", {})
    notes: list[str] = []

    status_ok = run_result.get("status") == "completed"
    report_ok = bool(run_result.get("report_md"))
    if grader.get("artifact_exists") == "report" and not report_ok:
        notes.append("missing report artifact")
    success = status_ok and report_ok

    expected_tools = set(case.get("expected_tools", []))
    used_tools = {tc.get("tool", "") for tc in run_result.get("tool_calls", [])}
    tool_selection = (
        len(expected_tools & used_tools) / len(expected_tools | used_tools)
        if expected_tools or used_tools else 1.0
    )
    tool_calls = run_result.get("tool_calls", [])
    tool_exec = (len([tc for tc in tool_calls if tc.get("status") == "ok"]) / len(tool_calls)) if tool_calls else 1.0

    citations = run_result.get("citations", [])
    verified = [c for c in citations if c.get("verified")]
    citation_precision = (len(verified) / len(citations)) if citations else (1.0 if not case.get("grader", {}).get("min_citations") else 0.0)
    hallucination_penalty = 1 - citation_precision

    min_citations = int(grader.get("min_citations", 0))
    if min_citations and len(verified) < min_citations:
        notes.append(f"expected >= {min_citations} verified citations, got {len(verified)}")
        success = False
    min_experiments = int(grader.get("min_experiments", 0))
    experiments = run_result.get("experiments", [])
    if min_experiments and sum(1 for e in experiments if e.get("status") == "success") < min_experiments:
        notes.append(f"expected >= {min_experiments} successful experiments")
        success = False

    metrics = run_result.get("metrics", {})
    repairs = int(metrics.get("repairs", 0))
    recovery = 1.0 if (repairs and success) else (0.0 if repairs else 1.0)

    groundedness = citation_precision  # same URL-grounding signal at run level
    return CaseResult(
        case_id=case["id"], success=success, tool_selection=round(tool_selection, 3),
        tool_execution_success=round(tool_exec, 3), citation_precision=round(citation_precision, 3),
        groundedness=round(groundedness, 3), recovery=round(recovery, 3),
        hallucination_penalty=round(hallucination_penalty, 3),
        latency_s=float(metrics.get("latency_s", 0.0)), cost_usd=float(metrics.get("cost_usd", 0.0)),
        notes=notes,
    )


def aggregate(results: list[CaseResult]) -> dict[str, float]:
    n = max(len(results), 1)
    return {
        "task_success_rate": sum(r.success for r in results) / n,
        "tool_selection_accuracy": sum(r.tool_selection for r in results) / n,
        "tool_execution_success": sum(r.tool_execution_success for r in results) / n,
        "citation_precision": sum(r.citation_precision for r in results) / n,
        "groundedness": sum(r.groundedness for r in results) / n,
        "recovery_rate": sum(r.recovery for r in results) / n,
        "avg_latency_s": sum(r.latency_s for r in results) / n,
        "avg_cost_usd": sum(r.cost_usd for r in results) / n,
        "n_cases": len(results),
    }

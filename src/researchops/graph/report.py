"""Deterministic report generation from run state — no LLM, fully auditable."""

from __future__ import annotations

from typing import Any

from ..core.types import utcnow


def build_report(state: dict[str, Any], metrics: dict[str, Any], review: dict[str, Any] | None = None) -> str:
    goal = state.get("user_goal", "(no goal)")
    lines: list[str] = []
    lines.append("# ResearchOps Report")
    lines.append("")
    lines.append(f"**Generated:** {utcnow().isoformat()}  ")
    lines.append(f"**Status:** {state.get('status', 'unknown')}")
    lines.append("")
    lines.append("## Goal")
    lines.append("")
    lines.append(str(goal))
    reqs = state.get("requirements") or []
    if reqs:
        lines.append("")
        lines.append("## Requirements")
        lines.append("")
        lines.extend(f"- {r}" for r in reqs)

    plan = state.get("plan") or []
    if plan:
        lines.append("")
        lines.append("## Plan & Execution")
        lines.append("")
        lines.append("| Task | Kind | Status |")
        lines.append("|------|------|--------|")
        for t in plan:
            lines.append(f"| {t.get('title', '')} | {t.get('kind', '')} | {t.get('status', '')} |")

    outputs = state.get("task_outputs") or {}
    research_outputs = {k: v for k, v in outputs.items() if v.get("kind") == "research"}
    if research_outputs:
        lines.append("")
        lines.append("## Findings")
        for v in research_outputs.values():
            lines.append("")
            lines.append(str(v.get("summary", ""))[:4000])

    repos = state.get("repositories") or []
    if repos:
        lines.append("")
        lines.append("## Repositories Analyzed")
        for r in repos:
            lines.append(f"- **{r.get('name', '')}** — {r.get('summary', '')[:300]}")

    citations = state.get("citations") or []
    if citations:
        lines.append("")
        lines.append("## Citations")
        lines.append("")
        for c in citations:
            mark = "✅" if c.get("verified") else "⚠️"
            lines.append(f"- {mark} [{c.get('title', 'source')}]({c.get('url', '')}) — {c.get('claim', '')[:200]}")

    experiments = state.get("experiments") or []
    if experiments:
        lines.append("")
        lines.append("## Experiments")
        for e in experiments:
            lines.append("")
            lines.append(f"### {e.get('name', 'experiment')} — {e.get('status', '')}")
            if e.get("command"):
                lines.append("")
                lines.append(f"```bash\n{e['command']}\n```")
            metrics_d = e.get("metrics") or {}
            if metrics_d:
                lines.append("")
                lines.append("| Metric | Value |")
                lines.append("|--------|-------|")
                lines.extend(f"| {k} | {v} |" for k, v in metrics_d.items())
            if e.get("log_excerpt"):
                lines.append("")
                lines.append(f"<details><summary>logs</summary>\n\n```\n{e['log_excerpt'][:2000]}\n```\n\n</details>")

    errors = state.get("errors") or []
    if errors:
        lines.append("")
        lines.append("## Failures & Repairs")
        for e in errors:
            lines.append(f"- `{e.get('node', '')}`: {e.get('message', '')[:300]}")
        if state.get("repair_attempts"):
            lines.append(f"- repair attempts: {state['repair_attempts']}")

    if review:
        lines.append("")
        lines.append("## Review")
        lines.append("")
        lines.append(f"- approved: **{review.get('approved')}**  ")
        lines.append(f"- confidence: **{review.get('confidence', 0):.2f}**")
        for issue in review.get("issues", []):
            lines.append(f"- issue: {issue}")

    lines.append("")
    lines.append("## Run Telemetry")
    lines.append("")
    lines.append(f"- tool calls: {metrics.get('tool_calls', 0)} (failed {metrics.get('failed_calls', 0)}, retries {metrics.get('retries', 0)})  ")
    lines.append(f"- tokens: {metrics.get('input_tokens', 0)} in / {metrics.get('output_tokens', 0)} out  ")
    lines.append(f"- cost: **${metrics.get('cost_usd', 0):.4f}**  ")
    lines.append(f"- latency: {metrics.get('latency_s', 0):.1f}s")

    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append("- Experiments run sandboxed (no network by default); results reflect the sandbox environment.")
    lines.append("- Citation marks: ✅ URL appeared in verified tool output, ⚠️ URL was asserted but not observed.")
    return "\n".join(lines)

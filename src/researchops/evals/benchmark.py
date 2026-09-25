"""ResearchOpsBench runner: executes dataset cases end-to-end and emits the
metrics table. In mock mode (default) this is a pipeline smoke benchmark —
NOT a model-quality claim. Point RESEARCHOPS_LLM_PROVIDER=openai with real
keys to measure genuine agent quality.

Usage:
    python -m researchops.evals.benchmark [--out results/baseline.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from ..core.types import new_id
from ..memory.store import MemoryStore
from ..runtime import build_run_context
from ..workers.runner import execute_run
from .graders import aggregate, grade, load_dataset


async def run_case(case: dict, settings: Settings, store: MemoryStore) -> dict:
    task_id = new_id("task")
    run_id = f"run_{task_id.split('_', 1)[-1]}"
    await store.create_task(task_id, case["goal"], case.get("requirements", []), auto_approve=True)
    await store.create_run(run_id, task_id)

    ctx = None
    if settings.llm_provider == "mock":
        # pipeline smoke: deterministic offline stubs + scripted provider
        from .offline import apply_offline

        ctx = await build_run_context(settings, store, run_id, task_id, case["goal"], case.get("requirements", []), True)
        apply_offline(ctx, case.get("kind", "research"))
    await execute_run(store, settings, run_id, ctx=ctx)

    run = await store.get_run(run_id)
    if run is None:
        return {"status": "failed", "report_md": "", "metrics": {}, "tool_calls": [], "citations": [], "experiments": []}
    import json as _json

    trace = run.trace_json if isinstance(run.trace_json, dict) else _json.loads(run.trace_json or "{}")
    tool_calls = [
        {"tool": r.tool, "status": r.status}
        for r in await store_list_tool_calls(store, run_id)
    ]
    citations = _citations_from_report(run.report_md or "")
    experiments = _experiments_from_report(run.report_md or "")
    metrics = run.metrics if isinstance(run.metrics, dict) else _json.loads(run.metrics or "{}")
    return {
        "status": run.status, "report_md": run.report_md or "", "metrics": metrics,
        "tool_calls": tool_calls, "citations": citations, "experiments": experiments,
        "trace": trace,
    }


async def store_list_tool_calls(store: MemoryStore, run_id: str):
    from sqlalchemy import select

    from ..memory.store import ToolCallRow

    async with store.session_factory() as s:
        rows = await s.execute(select(ToolCallRow).where(ToolCallRow.run_id == run_id))
        return list(rows.scalars())


def _citations_from_report(md: str) -> list[dict]:
    import re

    out = []
    for m in re.finditer(r"^- (✅|⚠️) \[([^\]]*)\]\((https?://[^)]+)\)", md, re.M):
        out.append({"title": m.group(2), "url": m.group(3), "verified": m.group(1) == "✅"})
    return out


def _experiments_from_report(md: str) -> list[dict]:
    import re

    out = []
    for m in re.finditer(r"^### (.+?) — (\w+)$", md, re.M):
        out.append({"name": m.group(1), "status": m.group(2)})
    return out


async def run_benchmark(limit: int = 0, settings: Settings | None = None) -> dict:
    settings = settings or Settings(llm_provider="mock", approval_auto=True)
    cases = load_dataset()
    if limit:
        cases = cases[:limit]
    store = MemoryStore(settings.database_url)
    await store.connect()
    results = []
    try:
        for case in cases:
            started = time.monotonic()
            run_result = await run_case(case, settings, store)
            result = grade(case, run_result)
            result.latency_s = round(time.monotonic() - started, 2)
            results.append(result)
    finally:
        await store.disconnect()
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "provider": settings.llm_provider,
            "cases": [r.to_dict() for r in results], "summary": aggregate(results)}


def format_table(summary: dict) -> str:
    return "\n".join([
        "ResearchOpsBench",
        "",
        f"Task success rate       {summary['task_success_rate'] * 100:5.1f}%",
        f"Tool selection accuracy {summary['tool_selection_accuracy'] * 100:5.1f}%",
        f"Tool execution success  {summary['tool_execution_success'] * 100:5.1f}%",
        f"Citation precision      {summary['citation_precision'] * 100:5.1f}%",
        f"Groundedness            {summary['groundedness'] * 100:5.1f}%",
        f"Recovery rate           {summary['recovery_rate'] * 100:5.1f}%",
        f"Avg latency             {summary['avg_latency_s']:7.1f} s",
        f"Avg cost                ${summary['avg_cost_usd']:6.4f}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ResearchOpsBench")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args()
    report = asyncio.run(run_benchmark(limit=args.limit))
    print(format_table(report["summary"]))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2))
        print(f"\nsaved → {args.out}")


if __name__ == "__main__":
    main()

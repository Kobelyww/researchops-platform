"""The six ResearchOps agents. Each one is a small, focused contract over the
shared tool-calling loop — routing and coordination live in the graph, not here.
"""

from __future__ import annotations

import json

from ..core.types import TaskNode
from .loop import Agent, RunContext, extract_json_objects


class PlannerAgent(Agent):
    name = "planner"
    description = "Decomposes a research goal into a small task graph (max 8 tasks)."
    task_kind = "planning"

    def system_prompt(self) -> str:
        return super().system_prompt() + (
            "\nRespond with ONLY a JSON object: {\"tasks\": [{\"id\": \"t1\", "
            "\"kind\": \"research|repository|code|experiment\", \"title\": str, "
            "\"description\": str, \"depends_on\": [ids]}]}. "
            "Kinds: research (find papers/web evidence), repository (clone+analyze a "
            "GitHub repo), code (write or repair code), experiment (run commands to "
            "produce metrics). Prefer 2-5 tasks."
        )

    async def plan(self, ctx: RunContext, feedback: list[str] | None = None) -> list[TaskNode]:
        instruction = (
            f"Goal: {ctx.goal}\nRequirements: {json.dumps(ctx.requirements)}\n"
            + (f"Operator feedback to incorporate: {json.dumps(feedback)}\n" if feedback else "")
            + "Produce the task graph JSON now."
        )
        result = await self.run(ctx, instruction)
        for obj in extract_json_objects(result.output):
            tasks_raw = obj.get("tasks")
            if isinstance(tasks_raw, list) and tasks_raw:
                tasks = []
                for i, t in enumerate(tasks_raw[:8]):
                    kind = str(t.get("kind", "research"))
                    if kind not in {"research", "repository", "code", "experiment"}:
                        kind = "research"
                    tasks.append(TaskNode(
                        id=str(t.get("id", f"t{i + 1}")), kind=kind,  # type: ignore[arg-type]
                        title=str(t.get("title", f"task {i + 1}"))[:200],
                        description=str(t.get("description", ""))[:1000],
                        depends_on=[str(d) for d in t.get("depends_on", [])][:8],
                    ))
                return tasks
        # deterministic fallback: a minimal sane plan (never fail the run at planning)
        return [
            TaskNode(id="t1", kind="research", title="Research the goal"),
            TaskNode(id="t2", kind="experiment", title="Run a baseline check", depends_on=["t1"]),
        ]


class ResearchAgent(Agent):
    name = "researcher"
    description = "Finds papers and web evidence, produces cited findings."
    allowed_tools = ["search_papers", "fetch_paper", "search_citations", "fetch_url", "browse_page", "fs_write", "memory_search"]

    def system_prompt(self) -> str:
        return super().system_prompt() + (
            "\nEnd your final answer with a fenced JSON block: {\"summary\": str, "
            "\"citations\": [{\"claim\": str, \"title\": str, \"url\": str}]}. "
            "Every factual claim needs a citation with a real URL you actually retrieved."
        )


class RepositoryAgent(Agent):
    name = "repo_agent"
    description = "Clones and analyzes GitHub repositories: structure, deps, entrypoints."
    allowed_tools = ["github_clone", "github_inspect", "fs_read", "fs_list"]

    def system_prompt(self) -> str:
        return super().system_prompt() + (
            "\nUse github_clone then github_inspect. End with a fenced JSON block: "
            "{\"repo_url\": str, \"summary\": str, \"entrypoints\": [str], \"install_cmd\": str}."
        )


class CoderAgent(Agent):
    name = "coder"
    description = "Reads, writes and repairs code in the sandboxed workspace, then tests it."
    allowed_tools = ["fs_read", "fs_write", "fs_list", "run_command", "run_python"]

    def system_prompt(self) -> str:
        return super().system_prompt() + (
            "\nWork only inside the workspace. After writing code, run it to verify. "
            "End with a fenced JSON block: {\"summary\": str, \"files\": [paths], \"tests_passed\": bool}."
        )


class ExperimenterAgent(Agent):
    name = "experimenter"
    description = "Builds the environment, runs experiments in the sandbox, parses metrics."
    allowed_tools = ["run_command", "run_python", "fs_read", "fs_write", "fs_list", "memory_search"]

    def system_prompt(self) -> str:
        return super().system_prompt() + (
            "\nCommands run sandboxed with no network by default. Parse real numbers "
            "from outputs — never invent metrics. End with a fenced JSON block: "
            "{\"experiment\": str, \"command\": str, \"status\": \"success|failed\", "
            "\"metrics\": {\"<name>\": number}, \"log_excerpt\": str}."
        )


class ReviewerAgent(Agent):
    name = "reviewer"
    description = "Verifies claims against evidence, scores confidence, blocks weak reports."
    allowed_tools = ["memory_search"]
    task_kind = "review"

    def system_prompt(self) -> str:
        return super().system_prompt() + (
            "\nEnd with a fenced JSON block: {\"approved\": bool, \"confidence\": 0.0-1.0, "
            "\"issues\": [str]}. Be strict: unverifiable claims lower confidence."
        )

    async def review(
        self, ctx: RunContext, findings: str, experiments: str, grounded_urls: set[str], citations: list[dict]
    ) -> dict:
        citation_lines = "\n".join(
            f"- {c.get('title', '')} {c.get('url', '')} {'VERIFIED_URL_SEEN' if c.get('url') in grounded_urls else 'URL_NOT_IN_EVIDENCE'}"
            for c in citations[:30]
        )
        instruction = (
            f"Goal: {ctx.goal}\n\nFindings:\n{findings[:6000]}\n\nExperiments:\n{experiments[:3000]}\n\n"
            f"Citations (VERIFIED_URL_SEEN means the URL appeared in actual tool output):\n{citation_lines}\n\n"
            "Review now."
        )
        result = await self.run(ctx, instruction)
        for obj in extract_json_objects(result.output):
            if "approved" in obj:
                obj.setdefault("confidence", 0.5)
                obj.setdefault("issues", [])
                return {"approved": bool(obj["approved"]), "confidence": float(obj["confidence"]), "issues": [str(i) for i in obj["issues"]][:10]}
        # deterministic fallback review
        verified = sum(1 for c in citations if c.get("url") in grounded_urls)
        confidence = verified / max(len(citations), 1)
        return {"approved": confidence >= 0.5 and bool(experiments.strip()), "confidence": confidence, "issues": []}

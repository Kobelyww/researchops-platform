"""Offline benchmark support: deterministic tool stubs + scripted mock
provider per case kind. Used ONLY when llm_provider == "mock" so the
benchmark exercises the full pipeline (routing, tools, gateway, HITL,
reporting) with zero network and zero API cost. These runs are pipeline
smoke tests, not model-quality measurements.
"""

from __future__ import annotations

from ..tools.registry import Tool

FAKE_PAPERS = [
    {"id": "2401.00001", "title": "Contrastive Learning for Cross-lingual Speaker Verification",
     "url": "https://arxiv.org/abs/2401.00001", "abstract": "Contrastive objectives improve cross-lingual robustness.",
     "authors": ["A. Author"], "year": 2024},
    {"id": "2402.00002", "title": "Reproducibility in Speech Model Research",
     "url": "https://arxiv.org/abs/2402.00002", "abstract": "A study of baseline reproduction failures.",
     "authors": ["C. Author"], "year": 2024},
]

REPO_URL = "https://github.com/example/tiny-asr"
REPO_PATH = "repos/tiny-asr"

REVIEWER_OK = ("final", '```json {"approved": true, "confidence": 0.9, "issues": []} ```')


async def _fake_search_papers(tctx, query: str, max_results: int = 8):
    return FAKE_PAPERS[: max(1, min(max_results, len(FAKE_PAPERS)))]


async def _fake_github_clone(tctx, url: str, branch: str | None = None):
    import os

    dest = tctx.workspace / REPO_PATH
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "README.md").write_text("# tiny-asr\n\nTiny speaker verification training repo.\n\n## Usage\npython train.py\n")
    (dest / "requirements.txt").write_text("torch>=2.0\nnumpy\nsoundfile\n")
    (dest / "train.py").write_text("print('training stub')\n")
    (dest / "run.sh").write_text("#!/bin/bash\npython train.py\n")
    _ = os  # silence linters in stub
    return {"path": REPO_PATH, "cached": dest.exists() and len(list(dest.iterdir())) > 4}


SCRIPTS: dict[str, dict[str, list[tuple]]] = {
    "research": {
        "planner": [("final", '{"tasks": [{"id": "t1", "kind": "research", "title": "Survey the topic"}]}')],
        "researcher": [
            ("tool", "search_papers", {"query": "topic"}),
            ("final", 'Findings below. ```json {"summary": "Contrastive learning improves cross-lingual speaker '
                      'verification robustness according to recent work.", "citations": ['
                      '{"claim": "contrastive objectives improve cross-lingual robustness", '
                      '"title": "Contrastive Learning for Cross-lingual Speaker Verification", '
                      '"url": "https://arxiv.org/abs/2401.00001"}]} ```'),
        ],
        "reviewer": [REVIEWER_OK],
    },
    "repository": {
        "planner": [("final", '{"tasks": [{"id": "t1", "kind": "repository", "title": "Clone and analyze repo"}]}')],
        "repo_agent": [
            ("tool", "github_clone", {"url": REPO_URL}),
            ("tool", "github_inspect", {"repo_path": REPO_PATH}),
            ("final", f'```json {{"repo_url": "{REPO_URL}", "summary": "Small training repo with torch deps; entrypoint train.py.", '
                      '"entrypoints": ["train.py"], "install_cmd": "pip install -r requirements.txt"} ```'),
        ],
        "reviewer": [REVIEWER_OK],
    },
    "code": {
        "planner": [("final", '{"tasks": [{"id": "t1", "kind": "code", "title": "Write and verify script"}]}')],
        "coder": [
            ("tool", "fs_write", {"path": "compute_metrics.py", "content": "print('acc=0.9')\n"}),
            ("tool", "run_python", {"code": "exec(open('compute_metrics.py').read())"}),
            ("final", '```json {"summary": "wrote and executed metrics script", "files": ["compute_metrics.py"], "tests_passed": true} ```'),
        ],
        "reviewer": [REVIEWER_OK],
    },
    "experiment": {
        "planner": [("final", '{"tasks": [{"id": "t1", "kind": "experiment", "title": "Run baseline"}]}')],
        "experimenter": [
            ("tool", "run_command", {"command": "echo 'acc=0.82' > metrics.txt && cat metrics.txt"}),
            ("final", '```json {"experiment": "baseline", "command": "echo", "status": "success", '
                      '"metrics": {"accuracy": 0.82}, "log_excerpt": "acc=0.82"} ```'),
        ],
        "reviewer": [REVIEWER_OK],
    },
    "e2e": {},
}

SCRIPTS["e2e"] = {
    "planner": [("final", '{"tasks": ['
                          '{"id": "t1", "kind": "research", "title": "Survey papers"}, '
                          '{"id": "t2", "kind": "experiment", "title": "Run baseline", "depends_on": ["t1"]}]}')],
    "researcher": SCRIPTS["research"]["researcher"],
    "experimenter": SCRIPTS["experiment"]["experimenter"],
    "reviewer": [REVIEWER_OK],
}


def apply_offline(ctx, kind: str) -> None:
    """Swap network-bound tools for deterministic stubs and script the mock LLM."""
    ctx.registry.tools["search_papers"] = Tool(
        name="search_papers", description="offline arXiv stub", timeout_s=5,
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        handler=_fake_search_papers,
    )
    ctx.registry.tools["github_clone"] = Tool(
        name="github_clone", description="offline git clone stub", timeout_s=5,
        parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        handler=_fake_github_clone,
    )
    scripts = SCRIPTS.get(kind, SCRIPTS["research"])
    ctx.llm.default_provider.scripts.update(scripts)

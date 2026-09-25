"""GitHub tools: shallow clone, deterministic repo inspection, PR creation.

Inspection (tree, README, dependencies, entrypoint candidates) is pure
deterministic code — no LLM required — which makes it cheap and testable.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from ..core.errors import ToolError
from .registry import ToolExecContext, tool

GITHUB_API = "https://api.github.com"

ENTRYPOINT_HINTS = ["main.py", "run.py", "train.py", "app.py", "cli.py", "setup.py", "pyproject.toml", "Makefile"]


@tool(name="github_clone", description="Shallow-clone a public GitHub repo into the workspace under repos/<name>.", parameters={
    "type": "object",
    "properties": {"url": {"type": "string"}, "branch": {"type": "string", "description": "optional branch"}},
    "required": ["url"]}, timeout_s=120)
async def github_clone(tctx: ToolExecContext, url: str, branch: str | None = None) -> dict:
    m = re.match(r"github\.com[:/](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(\.git)?/?$", url.replace("https://", "").replace("http://", ""))
    if not m:
        raise ToolError(f"not a GitHub URL: {url}")
    name = m.group("repo")
    dest = tctx.workspace / "repos" / name
    if dest.exists() and any(dest.iterdir()):
        return {"path": str(dest.relative_to(tctx.workspace)), "cached": True}
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = f"git clone --depth 1 {(' -b ' + branch) if branch else ''} {url} {dest}"
    result = await tctx.sandbox.run_command(cmd, timeout_s=90)
    if result.exit_code != 0:
        raise ToolError(f"git clone failed: {result.stderr[-500:]}")
    return {"path": str(dest.relative_to(tctx.workspace)), "cached": False}


def inspect_repo_dir(path: Path) -> dict:
    """Deterministic repository analysis (no LLM)."""
    files = [p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts][:2000]
    tree = sorted(str(p.relative_to(path)) for p in files)[:200]
    readme = next((f for f in files if f.name.upper().startswith("README")), None)
    readme_head = ""
    if readme:
        readme_head = "\n".join(readme.read_text(errors="replace").splitlines()[:60])
    deps: list[str] = []
    for marker in ("requirements.txt",):
        mf = path / marker
        if mf.is_file():
            deps = [ln.strip() for ln in mf.read_text(errors="replace").splitlines() if ln.strip() and not ln.startswith("#")][:60]
    pyproject = path / "pyproject.toml"
    if pyproject.is_file():
        deps += re.findall(r'"([\w.-]+?)(?:[<>=!~].*)?"', pyproject.read_text(errors="replace"))[:60]
    entrypoints = [t for t in tree if Path(t).name in ENTRYPOINT_HINTS or Path(t).name == "README.md"]
    languages: dict[str, int] = {}
    for f in files:
        ext = f.suffix.lower() or "other"
        languages[ext] = languages.get(ext, 0) + 1
    return {
        "name": path.name,
        "file_count": len(files),
        "tree": tree,
        "readme_head": readme_head,
        "dependencies": deps,
        "entrypoints": entrypoints,
        "top_extensions": sorted(languages.items(), key=lambda kv: -kv[1])[:8],
    }


@tool(name="github_inspect", description="Deterministically inspect a cloned repo: tree, README, deps, entrypoints.", parameters={
    "type": "object", "properties": {"repo_path": {"type": "string", "description": "workspace-relative path"}},
    "required": ["repo_path"]}, timeout_s=30)
async def github_inspect(tctx: ToolExecContext, repo_path: str) -> dict:
    root = (tctx.workspace / repo_path).resolve()
    ws = tctx.workspace.resolve()
    if not str(root).startswith(str(ws)) or not root.is_dir():
        raise ToolError(f"repo not found in workspace: {repo_path}")
    return inspect_repo_dir(root)


@tool(name="github_create_pull_request", description="Create a pull request on GitHub. HIGH-RISK: requires explicit approval.", parameters={
    "type": "object",
    "properties": {
        "repo": {"type": "string", "description": "owner/name"},
        "head": {"type": "string"}, "base": {"type": "string"},
        "title": {"type": "string"}, "body": {"type": "string"},
    },
    "required": ["repo", "head", "base", "title"]}, timeout_s=30)
async def github_create_pull_request(tctx: ToolExecContext, repo: str, head: str, base: str, title: str, body: str = "") -> dict:
    import os

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise ToolError("GITHUB_TOKEN not configured")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{repo}/pulls",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"title": title, "head": head, "base": base, "body": body},
        )
    if resp.status_code >= 300:
        raise ToolError(f"PR creation failed: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    return {"url": data.get("html_url", ""), "number": data.get("number")}


GITHUB_TOOLS = [github_clone, github_inspect, github_create_pull_request]

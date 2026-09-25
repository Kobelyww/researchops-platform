"""mcp-github — GitHub automation over MCP.

Tools: clone_repo, inspect_repo, create_branch, commit_files, create_pull_request.
Read-only inspection works without auth; write operations need GITHUB_TOKEN.
"""

from __future__ import annotations

import re

import httpx

from .common import make_server, run_server

server = make_server(
    "researchops-github",
    "GitHub automation: shallow clone, deterministic inspection, branch/commit/PR via REST API.",
)

GITHUB_API = "https://api.github.com"


def _parse_repo(url: str) -> tuple[str, str]:
    m = re.match(r"github\.com[:/](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(\.git)?/?$", url.replace("https://", ""))
    if not m:
        raise ValueError(f"not a GitHub URL: {url}")
    return m.group("owner"), m.group("repo")


@server.tool()
async def clone_repo(url: str, branch: str | None = None) -> dict:
    """Shallow-clone a repo into the shared workspace under repos/<name>."""
    from ..config import load_settings
    from ..sandbox.manager import create_sandbox
    from ..tools.github import github_clone
    from ..tools.registry import ToolExecContext

    settings = load_settings()
    workspace = settings.workspace_path / "mcp-github"
    sandbox = create_sandbox(workspace, settings.sandbox_backend, settings.sandbox_image)
    await sandbox.ensure()
    ctx = ToolExecContext(run_id="mcp", workspace=workspace, sandbox=sandbox)
    return await github_clone(ctx, url=url, branch=branch)


@server.tool()
async def inspect_repo(repo_path: str) -> dict:
    """Deterministic inspection of a cloned repo (tree, README, deps, entrypoints)."""
    from ..config import load_settings
    from ..tools.github import github_inspect
    from ..tools.registry import ToolExecContext

    ctx = ToolExecContext(run_id="mcp", workspace=load_settings().workspace_path / "mcp-github")
    return await github_inspect(ctx, repo_path=repo_path)


def _auth_headers() -> dict[str, str]:
    import os

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise PermissionError("GITHUB_TOKEN not configured; write operations are unavailable")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


@server.tool()
async def create_branch(repo: str, base: str, branch: str) -> dict:
    """Create a branch from `base` (ref update via REST)."""
    owner, name = _parse_repo(repo) if "github.com" in repo else _split(repo)
    async with httpx.AsyncClient(timeout=30) as client:
        ref = await client.get(f"{GITHUB_API}/repos/{owner}/{name}/git/ref/heads/{base}", headers=_auth_headers())
        ref.raise_for_status()
        sha = ref.json()["object"]["sha"]
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{name}/git/refs",
            headers=_auth_headers(), json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"create_branch failed: {resp.status_code} {resp.text[:200]}")
    return {"branch": branch, "sha": sha}


@server.tool()
async def commit_files(repo: str, branch: str, files: list[dict], message: str) -> dict:
    """Commit a set of {path, content} files to a branch via the Git Data API."""
    owner, name = _parse_repo(repo) if "github.com" in repo else _split(repo)
    headers = _auth_headers()
    async with httpx.AsyncClient(timeout=60) as client:
        ref = await client.get(f"{GITHUB_API}/repos/{owner}/{name}/git/ref/heads/{branch}", headers=headers)
        ref.raise_for_status()
        base_sha = ref.json()["object"]["sha"]
        base_commit = (await client.get(f"{GITHUB_API}/repos/{owner}/{name}/git/commits/{base_sha}", headers=headers)).json()
        tree_sha = base_commit["tree"]["sha"]

        tree_items = []
        for f in files[:50]:
            blob = await client.post(f"{GITHUB_API}/repos/{owner}/{name}/git/blobs", headers=headers,
                                     json={"content": f.get("content", ""), "encoding": "utf-8"})
            blob.raise_for_status()
            tree_items.append({"path": f["path"], "mode": "100644", "type": "blob", "sha": blob.json()["sha"]})
        tree = await client.post(f"{GITHUB_API}/repos/{owner}/{name}/git/trees", headers=headers,
                                 json={"base_tree": tree_sha, "tree": tree_items})
        tree.raise_for_status()
        commit = await client.post(f"{GITHUB_API}/repos/{owner}/{name}/git/commits", headers=headers,
                                   json={"message": message, "tree": tree.json()["sha"], "parents": [base_sha]})
        commit.raise_for_status()
        update = await client.patch(f"{GITHUB_API}/repos/{owner}/{name}/git/refs/heads/{branch}", headers=headers,
                                    json={"sha": commit.json()["sha"]})
        update.raise_for_status()
    return {"commit_sha": commit.json()["sha"], "branch": branch, "files": len(tree_items)}


@server.tool()
async def create_pull_request(repo: str, head: str, base: str, title: str, body: str = "") -> dict:
    """Open a pull request. HIGH-RISK write; requires GITHUB_TOKEN."""
    owner, name = _parse_repo(repo) if "github.com" in repo else _split(repo)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{GITHUB_API}/repos/{owner}/{name}/pulls", headers=_auth_headers(),
                                 json={"title": title, "head": head, "base": base, "body": body})
    if resp.status_code >= 300:
        raise RuntimeError(f"PR creation failed: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    return {"url": data.get("html_url", ""), "number": data.get("number")}


def _split(repo: str) -> tuple[str, str]:
    parts = repo.strip("/").split("/")
    if len(parts) != 2:
        raise ValueError(f"expected owner/name, got: {repo}")
    return parts[0], parts[1]


if __name__ == "__main__":
    run_server(server)

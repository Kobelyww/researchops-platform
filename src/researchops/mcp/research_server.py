"""mcp-research — paper/web retrieval over MCP.

Tools: search_papers, fetch_paper, search_citations, get_metadata, fetch_url.
Same core functions the in-process tools use (arXiv + Semantic Scholar).
"""

from __future__ import annotations

from .common import make_server, run_server

server = make_server(
    "researchops-research",
    "Research retrieval: arXiv paper search, metadata, citation graphs, allowlisted web fetch.",
)


@server.tool()
async def search_papers(query: str, max_results: int = 8) -> list[dict]:
    """Search arXiv for papers matching a query."""
    from ..tools.registry import ToolExecContext
    from ..tools.search import search_papers as _impl

    ctx = ToolExecContext(run_id="mcp", workspace=_tmp_workspace())
    return await _impl(ctx, query=query, max_results=max_results)


@server.tool()
async def fetch_paper(paper_id: str) -> dict:
    """Fetch an arXiv paper's metadata + abstract by id or abs URL."""
    from ..tools.registry import ToolExecContext
    from ..tools.search import fetch_paper as _impl

    ctx = ToolExecContext(run_id="mcp", workspace=_tmp_workspace())
    return await _impl(ctx, paper_id=paper_id)


@server.tool()
async def search_citations(paper_id: str, limit: int = 10) -> list[dict]:
    """List papers citing the given Semantic Scholar / arXiv id."""
    from ..tools.registry import ToolExecContext
    from ..tools.search import search_citations as _impl

    ctx = ToolExecContext(run_id="mcp", workspace=_tmp_workspace())
    return await _impl(ctx, paper_id=paper_id, limit=limit)


@server.tool()
async def get_metadata(paper_id: str) -> dict:
    """Alias of fetch_paper returning id/title/authors/year/urls."""
    meta = await fetch_paper(paper_id)
    return {k: meta.get(k) for k in ("id", "title", "authors", "year", "url", "abstract") if k in meta}


@server.tool()
async def fetch_url(url: str) -> dict:
    """Fetch a page's text (domain allowlist enforced)."""
    from ..config import load_settings
    from ..tools.registry import ToolExecContext
    from ..tools.search import fetch_url as _impl

    settings = load_settings()
    ctx = ToolExecContext(run_id="mcp", workspace=_tmp_workspace(), browser_domains=settings.browser_domains)
    return await _impl(ctx, url=url)


def _tmp_workspace():
    from ..config import load_settings

    return load_settings().workspace_path / "mcp-research"


if __name__ == "__main__":
    run_server(server)

"""Custom MCP servers — the agent exposes the same core capabilities both as
in-process gateway tools and as standalone MCP servers (stdio transport):

    python -m researchops.mcp.research_server
    python -m researchops.mcp.experiment_server
    python -m researchops.mcp.github_server
"""

from .common import make_server, run_server

__all__ = ["make_server", "run_server"]

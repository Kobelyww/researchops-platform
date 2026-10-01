"""MCP server utilities shared by all three servers.

Tool logic lives in plain functions inside researchops.tools / sandbox, so the
MCP layer is a thin adapter: same core, two transports (direct tool-calling and
Model Context Protocol).
"""

from __future__ import annotations

import contextlib

from mcp.server.mcpserver import MCPServer

from ..config import load_settings
from ..sandbox.manager import SandboxPolicy, create_sandbox


def make_server(name: str, instructions: str) -> MCPServer:
    return MCPServer(name=name, instructions=instructions)


@contextlib.asynccontextmanager
async def experiment_tools():
    """Yields a sandbox bound to a per-session workspace (for the MCP server)."""
    settings = load_settings()
    workspace = settings.workspace_path / "mcp-experiment"
    sandbox = create_sandbox(
        workspace, settings.sandbox_backend, settings.sandbox_image,
        SandboxPolicy(timeout_s=settings.sandbox_timeout_s, mem_limit_mb=settings.sandbox_mem_limit_mb, cpus=settings.sandbox_cpus),
    )
    await sandbox.ensure()
    try:
        yield sandbox, workspace, settings
    finally:
        await sandbox.cleanup()


def run_server(server: MCPServer) -> None:
    """stdio transport entrypoint (`python -m researchops.mcp.<server>`)."""
    server.run(transport="stdio")

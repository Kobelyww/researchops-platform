"""Shell/python execution tools — always delegated to the SandboxManager,
never run raw subprocess calls from the agent itself.
"""

from __future__ import annotations

from .registry import ToolExecContext, tool


@tool(name="run_command", description="Run a shell command inside the sandboxed workspace.", parameters={
    "type": "object",
    "properties": {
        "command": {"type": "string"},
        "timeout_s": {"type": "integer", "description": "max seconds (default from sandbox policy)"},
    },
    "required": ["command"]}, timeout_s=180)
async def run_command(tctx: ToolExecContext, command: str, timeout_s: int | None = None) -> dict:
    result = await tctx.sandbox.run_command(command, timeout_s=timeout_s)
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-2000:],
        "duration_s": result.duration_s,
    }


@tool(name="run_python", description="Run a Python snippet inside the sandboxed workspace.", parameters={
    "type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}, timeout_s=180)
async def run_python(tctx: ToolExecContext, code: str) -> dict:
    result = await tctx.sandbox.run_python(code)
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-2000:],
        "duration_s": result.duration_s,
    }


SHELL_TOOLS = [run_command, run_python]

"""mcp-experiment — sandboxed experiment execution over MCP.

Tools: create_environment, run_command, run_python, get_gpu_status, read_logs,
terminate_job. Backed by the same SandboxManager as the in-process gateway.

Trust boundary: this server is operator-run infrastructure (outside the
agent's tool gateway), so `create_environment` gets network access for
package installs; command/python execution still runs without network.
Sandboxes are per-call and cleaned up automatically.
"""

from __future__ import annotations

from ..sandbox.policies import SandboxPolicy
from .common import make_server, run_server

server = make_server(
    "researchops-experiment",
    "Sandboxed experiment execution: environment creation, command/python execution, GPU status, logs.",
)


@server.tool()
async def create_environment(python_packages: list[str] | None = None) -> dict:
    """Prepare the sandboxed workspace; optionally pip-install packages (needs network)."""
    from ..config import load_settings
    from ..sandbox.manager import create_sandbox
    from ..sandbox.policies import SandboxPolicy

    settings = load_settings()
    workspace = settings.workspace_path / "mcp-experiment"

    if python_packages:
        net_sandbox = create_sandbox(
            workspace, settings.sandbox_backend, settings.sandbox_image,
            SandboxPolicy(timeout_s=600, mem_limit_mb=settings.sandbox_mem_limit_mb,
                          cpus=settings.sandbox_cpus, network_enabled=True),
        )
        await net_sandbox.ensure()
        try:
            result = await net_sandbox.run_command(f"pip install --quiet {' '.join(python_packages)}", timeout_s=500)
            return {"ok": result.ok, "stderr": result.stderr[-500:]}
        finally:
            await net_sandbox.cleanup()
    return {"ok": True, "note": "workspace ready (no packages requested)"}


@server.tool()
async def run_command(command: str, timeout_s: int = 120) -> dict:
    """Run a shell command inside the sandbox (network disabled)."""
    from ..config import load_settings
    from ..sandbox.manager import create_sandbox

    settings = load_settings()
    sandbox = create_sandbox(
        settings.workspace_path / "mcp-experiment", settings.sandbox_backend, settings.sandbox_image,
        SandboxPolicy(timeout_s=min(float(timeout_s), settings.sandbox_timeout_s),
                      mem_limit_mb=settings.sandbox_mem_limit_mb, cpus=settings.sandbox_cpus),
    )
    await sandbox.ensure()
    try:
        result = await sandbox.run_command(command, timeout_s=float(timeout_s))
        return {"exit_code": result.exit_code, "stdout": result.stdout[-4000:], "stderr": result.stderr[-2000:], "duration_s": result.duration_s}
    finally:
        await sandbox.cleanup()


@server.tool()
async def run_python(code: str) -> dict:
    """Run a Python snippet inside the sandbox."""
    from ..config import load_settings
    from ..sandbox.manager import create_sandbox

    settings = load_settings()
    sandbox = create_sandbox(
        settings.workspace_path / "mcp-experiment", settings.sandbox_backend, settings.sandbox_image,
        SandboxPolicy(timeout_s=settings.sandbox_timeout_s, mem_limit_mb=settings.sandbox_mem_limit_mb, cpus=settings.sandbox_cpus),
    )
    await sandbox.ensure()
    try:
        result = await sandbox.run_python(code)
        return {"exit_code": result.exit_code, "stdout": result.stdout[-4000:], "stderr": result.stderr[-2000:], "duration_s": result.duration_s}
    finally:
        await sandbox.cleanup()


@server.tool()
async def get_gpu_status() -> dict:
    """Report GPUs visible to the sandbox (empty when none)."""
    from ..config import load_settings
    from ..sandbox.manager import create_sandbox

    settings = load_settings()
    sandbox = create_sandbox(
        settings.workspace_path / "mcp-experiment", settings.sandbox_backend, settings.sandbox_image,
        SandboxPolicy(timeout_s=15, mem_limit_mb=settings.sandbox_mem_limit_mb, cpus=settings.sandbox_cpus),
    )
    await sandbox.ensure()
    try:
        return await sandbox.get_gpu_status()
    finally:
        await sandbox.cleanup()


@server.tool()
async def read_logs() -> str:
    """Read the tail of sandbox log files."""
    from ..config import load_settings

    settings = load_settings()
    log_dir = settings.workspace_path / "mcp-experiment" / "logs"
    if not log_dir.exists():
        return ""
    return "\n".join(p.read_text(errors="replace")[-2000:] for p in sorted(log_dir.glob("*"))[-5:])


@server.tool()
async def terminate_job() -> dict:
    """Signal the experiment session is finished (per-call sandboxes auto-clean)."""
    return {"ok": True, "note": "per-call sandboxes are torn down automatically"}


if __name__ == "__main__":
    run_server(server)

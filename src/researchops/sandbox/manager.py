"""Sandboxed command execution.

Two backends:
- LocalSandbox: subprocess with env allowlist + rlimits + timeout. Dev mode
  (e.g. macOS without a Docker daemon); still confined to the run workspace.
- DockerSandbox: one container per run — CPU/memory limits, network disabled,
  workspace bind-mounted. Production mode.

The agent NEVER spawns processes directly; it goes through the tool gateway,
which delegates here.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import SandboxError
from .policies import ENV_ALLOWLIST, SandboxPolicy


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def _sandbox_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ}
    env.setdefault("HOME", "/tmp")
    env.setdefault("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _apply_rlimits() -> None:  # pragma: no cover - runs in child preexec
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        cpu = resource.getrlimit(resource.RLIMIT_CPU)
        resource.setrlimit(resource.RLIMIT_CPU, (min(600, cpu[0] or 600),) * 2)
    except Exception:
        pass  # limits are best-effort; the hard timeout always applies


class LocalSandbox:
    backend = "local"

    def __init__(self, workspace: Path, policy: SandboxPolicy | None = None):
        self.workspace = workspace
        self.policy = policy or SandboxPolicy()

    async def ensure(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def run_command(self, command: str, timeout_s: float | None = None) -> SandboxResult:
        await self.ensure()
        timeout = min(timeout_s or self.policy.timeout_s, self.policy.timeout_s)
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace),
                env=_sandbox_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=_apply_rlimits if os.name == "posix" else None,
            )
        except OSError as exc:
            raise SandboxError(f"failed to spawn: {exc}") from exc
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            timed_out = False
        except asyncio.TimeoutError:
            proc.kill()
            out, err = await proc.communicate()
            timed_out = True
        return SandboxResult(
            exit_code=proc.returncode or 0,
            stdout=out.decode(errors="replace")[: self.policy.max_output_bytes],
            stderr=err.decode(errors="replace")[: self.policy.max_output_bytes],
            duration_s=round(time.monotonic() - started, 2),
            timed_out=timed_out,
        )

    async def run_python(self, code: str, timeout_s: float | None = None) -> SandboxResult:
        path = self.workspace / "_run_python_.py"
        path.write_text(code)
        return await self.run_command(f'python3 "{path.name}"', timeout_s=timeout_s)

    async def read_logs(self) -> str:
        log_dir = self.workspace / "logs"
        if not log_dir.exists():
            return ""
        return "\n".join(p.read_text(errors="replace")[-2000:] for p in sorted(log_dir.glob("*"))[-5:])

    async def get_gpu_status(self) -> dict:
        result = await self.run_command("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", timeout_s=10)
        if result.ok and result.stdout.strip():
            return {"gpus": [ln.strip() for ln in result.stdout.strip().splitlines()]}
        return {"gpus": [], "note": "no GPU visible to sandbox"}

    async def cleanup(self) -> None:  # nothing persistent for local backend
        return None


class DockerSandbox:
    """One container per run; requires the `docker` extra and a running daemon."""

    backend = "docker"

    def __init__(self, workspace: Path, image: str = "python:3.11-slim", policy: SandboxPolicy | None = None):
        self.workspace = workspace
        self.image = image
        self.policy = policy or SandboxPolicy()
        self._container = None

    async def _client(self):
        try:
            import docker  # type: ignore
        except ImportError as exc:
            raise SandboxError("docker extra not installed: pip install 'researchops-agent[docker]'") from exc
        return asyncio.to_thread(docker.from_env)  # type: ignore[return-value]

    async def ensure(self) -> None:
        if self._container is not None:
            return
        self.workspace.mkdir(parents=True, exist_ok=True)
        try:
            client = await self._client()
            container = await asyncio.to_thread(
                lambda: client().containers.run(  # type: ignore[union-attr]
                    self.image,
                    command="sleep infinity",
                    detach=True,
                    network_disabled=not self.policy.network_enabled,
                    mem_limit=f"{self.policy.mem_limit_mb}m",
                    nano_cpus=int(self.policy.cpus * 1e9),
                    security_opt=["no-new-privileges"],
                    volumes={str(self.workspace.resolve()): {"bind": "/workspace", "mode": "rw"}},
                    working_dir="/workspace",
                )
            )
            self._container = container
        except SandboxError:
            raise
        except Exception as exc:  # daemon down, image missing, ...
            raise SandboxError(f"docker sandbox unavailable: {exc}") from exc

    async def run_command(self, command: str, timeout_s: float | None = None) -> SandboxResult:
        await self.ensure()
        timeout = min(timeout_s or self.policy.timeout_s, self.policy.timeout_s)
        started = time.monotonic()
        code, demux = await asyncio.to_thread(
            lambda: self._container.exec_run(  # type: ignore[union-attr]
                ["bash", "-lc", f"timeout {int(timeout)}s {command}"],
                workdir="/workspace", demux=True,
            )
        )
        out, err = demux or (b"", b"")
        return SandboxResult(
            exit_code=int(code or 0),
            stdout=(out or b"").decode(errors="replace")[: self.policy.max_output_bytes],
            stderr=(err or b"").decode(errors="replace")[: self.policy.max_output_bytes],
            duration_s=round(time.monotonic() - started, 2),
        )

    async def run_python(self, code: str, timeout_s: float | None = None) -> SandboxResult:
        path = self.workspace / "_run_python_.py"
        path.write_text(code)
        return await self.run_command(f'python3 "{path.name}"', timeout_s=timeout_s)

    async def read_logs(self) -> str:
        return (await self.run_command("cat logs/* 2>/dev/null | tail -c 4000")).stdout

    async def get_gpu_status(self) -> dict:
        result = await self.run_command("nvidia-smi -L", timeout_s=10)
        return {"gpus": result.stdout.strip().splitlines() if result.ok else []}

    async def cleanup(self) -> None:
        if self._container is not None:
            try:
                await asyncio.to_thread(lambda: self._container.remove(force=True))  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            self._container = None


def create_sandbox(workspace: Path, backend: str, image: str, policy: SandboxPolicy):
    if backend == "docker":
        return DockerSandbox(workspace, image=image, policy=policy)
    return LocalSandbox(workspace, policy=policy)

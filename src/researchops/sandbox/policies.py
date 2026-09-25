"""Sandbox policies: resource limits and environment isolation."""

from __future__ import annotations

from dataclasses import dataclass

# Only these variables pass from the host into a sandboxed process.
# Secrets (API keys, tokens) NEVER propagate — the agent must not be able to
# read its own credentials through a shell.
ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "PYTHONUNBUFFERED", "TMPDIR", "HOME")

DEFAULT_SECCOMP_NOTE = "docker: network_mode=none, no-new-privileges, read-only secrets"


@dataclass
class SandboxPolicy:
    timeout_s: float = 120.0
    mem_limit_mb: int = 1024
    cpus: float = 1.0
    network_enabled: bool = False
    max_output_bytes: int = 1_000_000

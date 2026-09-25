"""Risk classification for tool calls — deterministic rules, not LLM judgment."""

from __future__ import annotations

from ..core.types import RiskLevel

# Command prefixes that are always HIGH risk (destructive / external side effects).
HIGH_COMMAND_PREFIXES = (
    "rm ", "rm\t", "sudo ", "mkfs", "dd ", "git push", "chmod 777",
    "curl -x post", "wget --post", "ssh ", "scp ",
)

# Commands with moderate side effects: install packages, clone repos, write via pipe.
MEDIUM_COMMAND_PREFIXES = ("pip install", "npm install", "git clone", "git commit", "make ", "python ", "python3 ", "bash ", "sh ")

# Tools whose default risk (before content inspection).
TOOL_DEFAULT_RISK: dict[str, RiskLevel] = {
    "fs_read": RiskLevel.LOW,
    "fs_list": RiskLevel.LOW,
    "search_papers": RiskLevel.LOW,
    "fetch_paper": RiskLevel.LOW,
    "search_citations": RiskLevel.LOW,
    "fetch_url": RiskLevel.LOW,
    "browse_page": RiskLevel.LOW,
    "memory_search": RiskLevel.LOW,
    "github_inspect": RiskLevel.LOW,
    "fs_write": RiskLevel.MEDIUM,
    "run_command": RiskLevel.MEDIUM,
    "run_python": RiskLevel.MEDIUM,
    "github_clone": RiskLevel.MEDIUM,
    "create_environment": RiskLevel.MEDIUM,
    "github_create_pull_request": RiskLevel.HIGH,
    "git_push": RiskLevel.HIGH,
    "send_email": RiskLevel.HIGH,
}


def _inspect_command(command: str) -> RiskLevel:
    cmd = command.strip().lower()
    if any(cmd.startswith(p) or f"&& {p}" in cmd or f"; {p}" in cmd for p in HIGH_COMMAND_PREFIXES):
        return RiskLevel.HIGH
    if any(cmd.startswith(p) or f"&& {p}" in cmd or f"; {p}" in cmd for p in MEDIUM_COMMAND_PREFIXES):
        return RiskLevel.MEDIUM
    # unknown commands run inside the sandbox: treat as medium (they execute code)
    return RiskLevel.MEDIUM


def classify(tool_name: str, args: dict) -> RiskLevel:
    """Classify the risk of a tool call. Content inspection can only escalate."""
    base = TOOL_DEFAULT_RISK.get(tool_name, RiskLevel.MEDIUM)
    if tool_name in {"run_command", "create_environment", "terminate_job"}:
        cmd_risk = _inspect_command(str(args.get("command", "")))
        if cmd_risk.rank > base.rank:
            return cmd_risk
        return base
    return base

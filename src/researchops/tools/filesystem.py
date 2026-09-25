"""Filesystem tools, confined to the run workspace (path-traversal safe)."""

from __future__ import annotations

from pathlib import Path

from ..core.errors import ToolError
from .registry import ToolExecContext, tool

MAX_WRITE_CHARS = 200_000


def _resolve_confined(workspace: Path, rel_path: str) -> Path:
    if not rel_path or rel_path.startswith("/"):
        raise ToolError(f"path must be workspace-relative, got: {rel_path!r}")
    root = workspace.resolve()
    target = (root / rel_path).resolve()
    if not str(target).startswith(str(root)):
        raise ToolError(f"path escapes workspace: {rel_path!r}")
    return target


@tool(name="fs_read", description="Read a text file from the run workspace.", parameters={
    "type": "object", "properties": {"path": {"type": "string", "description": "workspace-relative path"}},
    "required": ["path"]})
async def fs_read(tctx: ToolExecContext, path: str) -> str:
    target = _resolve_confined(tctx.workspace, path)
    if not target.is_file():
        raise ToolError(f"not a file: {path}")
    text = target.read_text(errors="replace")
    return text[:40_000]


@tool(name="fs_write", description="Write text content to a file in the run workspace (creates parents).", parameters={
    "type": "object",
    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"]})
async def fs_write(tctx: ToolExecContext, path: str, content: str) -> str:
    target = _resolve_confined(tctx.workspace, path)
    if len(content) > MAX_WRITE_CHARS:
        raise ToolError(f"content too large ({len(content)} chars > {MAX_WRITE_CHARS})")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return f"wrote {len(content)} chars to {path}"


@tool(name="fs_list", description="List files under a workspace directory.", parameters={
    "type": "object", "properties": {"path": {"type": "string", "description": "defaults to workspace root"}},
    "required": []})
async def fs_list(tctx: ToolExecContext, path: str = ".") -> list[str]:
    target = _resolve_confined(tctx.workspace, path)
    if not target.exists():
        raise ToolError(f"no such directory: {path}")
    return sorted(str(p.relative_to(tctx.workspace)) for p in target.rglob("*") if p.is_file())[:500]


FILESYSTEM_TOOLS = [fs_read, fs_write, fs_list]

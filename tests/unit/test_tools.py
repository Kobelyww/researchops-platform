"""Tool registry validation, workspace confinement, observation limits."""

from __future__ import annotations

import pytest

from researchops.core.errors import ToolError
from researchops.tools.filesystem import fs_list, fs_read, fs_write
from researchops.tools.registry import ToolExecContext, ToolRegistry


@pytest.fixture()
def tctx(tmp_path) -> ToolExecContext:
    return ToolExecContext(run_id="run_test", workspace=tmp_path)


@pytest.mark.asyncio()
async def test_fs_roundtrip_and_listing(tctx):
    assert "wrote" in await fs_write(tctx, path="docs/a.txt", content="hello world")
    assert (await fs_read(tctx, path="docs/a.txt")) == "hello world"
    listing = await fs_list(tctx, path=".")
    assert "docs/a.txt" in listing


@pytest.mark.asyncio()
async def test_fs_confines_paths(tctx):
    with pytest.raises(ToolError):
        await fs_write(tctx, path="../escape.txt", content="nope")
    with pytest.raises(ToolError):
        await fs_read(tctx, path="/etc/passwd")
    with pytest.raises(ToolError):
        await fs_list(tctx, path="../../")


@pytest.mark.asyncio()
async def test_registry_validation(tctx, tmp_path):
    reg = ToolRegistry()
    reg.register_fn(fs_write)
    with pytest.raises(ToolError):
        await reg.execute("fs_write", {"path": "x.txt"}, tctx)  # missing content
    with pytest.raises(ToolError):
        await reg.execute("fs_write", {"path": "x.txt", "content": 123}, tctx)  # wrong type
    with pytest.raises(ToolError):
        await reg.execute("nope", {}, tctx)  # unknown tool


def test_observation_truncation():
    long = ToolRegistry.observation("x" * 20000, max_chars=100)
    assert len(long) < 200 and "truncated" in long


def test_duplicate_names_rejected():
    reg = ToolRegistry()
    reg.register_fn(fs_read)
    with pytest.raises(ValueError):
        reg.register_fn(fs_read)


def test_schema_shape():
    reg = ToolRegistry()
    reg.register_fn(fs_write)
    schema = reg.schemas(["fs_write"])[0]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "fs_write"
    assert "content" in schema["function"]["parameters"]["properties"]

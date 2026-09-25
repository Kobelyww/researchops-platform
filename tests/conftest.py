"""Shared fixtures: isolated settings/store per test."""

from __future__ import annotations

import pytest

from researchops.config import Settings
from researchops.memory.store import MemoryStore


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        llm_provider="mock",
        execution_mode="worker",
        database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
        checkpoint_db=str(tmp_path / "ckpt.db"),
        workspace_root=str(tmp_path / "ws"),
        sandbox_backend="local",
        approval_auto=False,
        max_repair_attempts=1,
        max_tool_calls=100,
    )


@pytest.fixture()
async def store(settings) -> MemoryStore:
    s = MemoryStore(settings.database_url)
    await s.connect()
    yield s
    await s.disconnect()

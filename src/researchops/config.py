"""Central configuration (12-factor, env-driven)."""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESEARCHOPS_", env_file=".env", extra="ignore")

    app_name: str = "ResearchOps"
    execution_mode: str = "inline"  # inline | worker

    # Persistence
    database_url: str = "sqlite+aiosqlite:///./.data/researchops.db"
    checkpoint_db: str = "./.data/checkpoints.db"
    workspace_root: str = "./.data/workspaces"

    # API
    api_key: str = ""
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @cached_property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["*"]

    # LLM layer — provider "mock" runs fully offline (tests / demo).
    llm_provider: str = "mock"  # mock | openai
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 90.0
    model_routes: str = "{}"  # JSON: {"planning": "gpt-4o-mini", ...}

    # Embeddings
    embedding_provider: str = "hash"  # hash | openai
    embedding_model: str = "text-embedding-3-small"

    # Budget / guardrails
    max_cost_usd: float = 5.0
    max_minutes: float = 30.0
    max_tool_calls: int = 200
    approval_auto: bool = False
    max_repair_attempts: int = 2
    observation_max_chars: int = 8000

    # Sandbox
    sandbox_backend: str = "local"  # local | docker
    sandbox_image: str = "python:3.11-slim"
    sandbox_timeout_s: float = 120.0
    sandbox_mem_limit_mb: int = 1024
    sandbox_cpus: float = 1.0

    # Browser tool
    browser_allow_domains: str = "arxiv.org,en.wikipedia.org,github.com,huggingface.co"
    browser_max_pages: int = 10

    # Research sources
    arxiv_max_results: int = 8

    @field_validator("execution_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in {"inline", "worker"}:
            raise ValueError("execution_mode must be inline|worker")
        return v

    @cached_property
    def model_routes_map(self) -> dict[str, str]:
        try:
            return {k: str(v) for k, v in json.loads(self.model_routes).items()}
        except (json.JSONDecodeError, TypeError):
            return {}

    @cached_property
    def browser_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.browser_allow_domains.split(",") if d.strip()]

    @property
    def workspace_path(self) -> Path:
        p = Path(self.workspace_root)
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()

    @property
    def data_dir(self) -> Path:
        if self.database_url.startswith("sqlite"):
            db_path = self.database_url.split("///")[-1]
            d = Path(db_path).parent
        else:
            d = Path("./.data")
        d.mkdir(parents=True, exist_ok=True)
        return d


def load_settings() -> Settings:
    return Settings()

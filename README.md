# ResearchOps

**An open-source autonomous research & experiment engineering agent.**

```text
Research → Code → Execute → Evaluate → Report
```

ResearchOps takes a research goal like *"reproduce the baseline of this paper, run experiments, and generate a cited report"* and actually executes it: it plans a task graph, retrieves papers with grounded citations, clones and inspects repositories, runs experiments inside a sandboxed environment, diagnoses and repairs failures, and publishes a sign-off-gated technical report — with every tool call passing a policy gateway and every step observable.

| | |
|---|---|
| **Stateful orchestration** | LangGraph state machine with durable checkpoints, retries, and a diagnose→repair loop |
| **Human-in-the-loop** | Risk-classified approval gates (`interrupt()`-based) for risky tool calls and report publishing |
| **Guardrails** | Every tool call flows through a gateway: allowlist → risk classification → policy → audit → sandboxed execution |
| **Custom MCP servers** | 3 servers (research retrieval / sandboxed experiments / GitHub automation) sharing the same core as in-process tools |
| **Sandboxed execution** | Docker backend (network-off, CPU/mem limits) with a local dev fallback — agents never spawn raw processes |
| **Memory & retrieval** | Working/episodic/semantic memory, hybrid BM25+vector retrieval with RRF fusion |
| **Evaluation** | ResearchOpsBench: dataset, deterministic graders, benchmark runner, CI regression gate |
| **Observability** | Span-tree tracing (trace/run/agent/tool/latency/tokens/cost), per-run metrics, SSE live event stream |
| **Model routing** | Task-kind → model routing table (cheap models for extraction, strong ones for planning/review) |
| **Runs offline** | `llm_provider=mock` + deterministic stubs execute the entire pipeline with zero keys and zero network |

## Architecture

```text
                     ┌──────────────┐
                     │  Web (Next.js) │  live dashboard, approvals, metrics
                     └──────┬───────┘
                            │ SSE / REST
                     ┌──────▼───────┐
                     │  FastAPI API  │  tasks · runs · events · approvals
                     └──────┬───────┘
                     ┌──────▼───────┐
                     │    Worker     │  claims tasks, executes/resumes runs
                     └──────┬───────┘
              ┌─────────────▼──────────────┐
              │   LangGraph Orchestrator    │
              │   START→ingest→plan→select  │
              └──┬─────┬─────┬─────┬───────┘
                 ▼     ▼     ▼     ▼
            research repository code  synthesize
                 └─────┴─────┴─────┬─────┘
                                   ▼
                        experiment (sandboxed)
                                   ▼
                     evaluate ──fail──▶ diagnose ──▶ repair
                                   │ success
                                   ▼
                    approve (human sign-off gate)
                                   ▼
                          report / artifacts

   every agent tool call:  LLM → ToolGateway → policy/risk/budget/approval
                                 → MCP-equivalent core → sandbox / arXiv / GitHub
```

The design principle: **deterministic code owns everything that must be reliable** (routing, evaluation pre-checks, policy, risk, budgets, reports); **LLM agents only do the creative steps** (planning, research, coding, reviewing).

## Quickstart

### 1. Offline demo (no API keys, no network)

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/demo_offline.py
```

You'll see the full pipeline run live — planning, a cited research step, an experiment that pauses at the **approval gate**, resumes after sign-off, and publishes `report.md`.

### 2. API + dashboard

```bash
cp .env.example .env          # defaults run in mock mode; add keys for real LLMs
.venv/bin/python -m uvicorn researchops_api.main:app --port 8000
cd apps/web && npm install && npm run dev   # http://localhost:3000
```

Submit a goal at `http://localhost:3000`; the run page streams live events and shows the approval panel when the agent requests permission for a risky action.

### 3. Docker Compose (postgres + api + worker + web)

```bash
docker compose up --build          # core stack
docker compose --profile full up   # + postgres (pgvector) & redis
docker compose --profile worker up # + dedicated worker process
```

### 4. Switch to a real LLM

Any OpenAI-compatible endpoint works (OpenAI, DeepSeek, Together, vLLM, Ollama):

```bash
RESEARCHOPS_LLM_PROVIDER=openai
RESEARCHOPS_LLM_API_KEY=sk-...
RESEARCHOPS_LLM_MODEL=gpt-4o-mini
RESEARCHOPS_MODEL_ROUTES='{"planning":"gpt-4o","review":"gpt-4o","debugging":"gpt-4o"}'
```

## MCP servers

The same tool core that the gateway exposes in-process is also packaged as three standalone MCP servers (stdio):

```bash
python -m researchops.mcp.research_server     # search_papers, fetch_paper, search_citations, get_metadata, fetch_url
python -m researchops.mcp.experiment_server   # create_environment, run_command, run_python, get_gpu_status, read_logs
python -m researchops.mcp.github_server       # clone_repo, inspect_repo, create_branch, commit_files, create_pull_request
```

See [`mcp.config.example.json`](mcp.config.example.json) for a ready-made client config.

## Guardrails model

| Risk | Examples | Behaviour |
|---|---|---|
| LOW | read files, search papers, fetch allowlisted URLs | automatic |
| MEDIUM | write files, run sandbox commands, clone repos | human approval (or pre-approved via `auto_approve`) |
| HIGH | `rm`, `git push`, external POSTs, PR creation | explicit approval (headless mode needs `allow_high_risk_auto`) |

Additional layers: tool allowlist (unknown tools are denied), JSON-schema argument validation, prompt-injection scanning of tool observations (wrapped in `<untrusted_content>`, forged role tags hard-denied), per-run budget (cost / wall-clock / tool-call caps), env-var allowlisting so agents can never read their own credentials, and a full per-call audit trail.

## Evaluation — ResearchOpsBench

`src/researchops/evals/dataset/tasks.jsonl` ships 20 tasks across research / GitHub / coding / experiment / end-to-end categories, graded on task success, tool-selection accuracy, tool-execution success, citation precision, groundedness, recovery rate, latency and cost.

```bash
python -m researchops.evals.benchmark --limit 8 --out results/current.json
python -m researchops.evals.regression results/current.json --baseline results/baseline.json
```

**Current numbers (offline mock-mode pipeline smoke — NOT a model-quality claim):**

```text
ResearchOpsBench (8 cases, mock provider, deterministic stubs)

Task success rate       100.0%
Tool selection accuracy  93.8%
Tool execution success  100.0%
Citation precision      100.0%
Recovery rate           100.0%
Avg cost                $0.0000
```

These verify the harness itself (routing, gateway, HITL, grading, reporting). Running the benchmark with a real provider (`RESEARCHOPS_LLM_PROVIDER=openai`) produces the meaningful agent-quality numbers; the regression gate fails CI when quality drops beyond thresholds.

## Configuration

Everything is env-driven (prefix `RESEARCHOPS_`, see [`.env.example`](.env.example)): execution mode (`inline` vs dedicated `worker`), database (`sqlite` default, Postgres+pgvector in compose), sandbox backend (`local`/`docker`), budgets, model routes, browser domain allowlist, API key.

## Project layout

```text
researchops-agent/
├── src/researchops/
│   ├── agents/        # 6 agents + the framework-free tool-calling loop
│   ├── graph/         # LangGraph state, nodes, routing, workflow, reports
│   ├── mcp/           # 3 custom MCP servers (research/experiment/github)
│   ├── tools/         # registry, filesystem, shell, search, browser, github
│   ├── sandbox/       # local + docker backends, resource policies
│   ├── memory/        # store, hybrid retrieval (BM25+RRF), embeddings, episodic
│   ├── guardrails/    # policy engine, risk classifier, gateway, injection defense
│   ├── observability/ # tracing spans, metrics, cost accounting
│   ├── evals/         # ResearchOpsBench dataset, graders, benchmark, regression
│   └── workers/       # run executor + standalone worker loop
├── src/researchops_api/  # FastAPI gateway (SSE, approvals, traces)
├── apps/web/              # Next.js dashboard
├── tests/{unit,integration,e2e}/
├── docker/ + docker-compose.yml
└── .github/workflows/ci.yml
```

## Development

```bash
pip install -e ".[dev]"
pytest tests            # 27 tests, fully offline
ruff check src tests scripts
```

Optional extras: `.[docker]`, `.[postgres]`, `.[redis]`, `.[browser]` (Playwright), `.[otel]`.

## Roadmap

Tracked in beads (`bd ready`):

- [ ] Postgres + pgvector as the default production memory store
- [ ] Real-browser hardening (Playwright DOM extraction + vision fallback, injection canaries)
- [ ] GPU experiment scheduling (CUDA containers, multi-node queue)
- [ ] Expand ResearchOpsBench to the full 100-task suite with LLM-judge graders
- [ ] OpenTelemetry/Langfuse exporters behind the existing trace interface
- [ ] Cloud deployment (AWS) + demo videos of the 5 flagship scenarios

## License

MIT

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Unified AI Swarm Platform that supports four product loops (Certification Engine, Living Dossiers, AI Lab Observatory, Story Engine) using shared agents, shared data structures, shared orchestration, and shared publishing. See `PRD.MD` for full requirements.

Tech stack: Python, SQLite + filesystem storage, YAML graph definitions. Local-first execution, batch/scheduled runs. Multi-node hardware fleet with Ollama model serving.

## Build and Run Commands

```bash
# Install dependencies
pip install -e ".[dev]"

# Run product loops
python -m scripts.run_cert --cert_id <id>
python -m scripts.run_dossier --topic_id <id>
python -m scripts.run_lab --suite_id <id>
python -m scripts.run_story --world_id <id> --sources seed.json --model-call ollama:qwen2.5:7b
python -m scripts.run_story --world_id <id> --sources seed.json --tiered  # creative→Haiku, extraction→local Ollama

# Unified router CLI (routes through tiered dispatch)
python -m scripts.run_router "/cert az-104"
python -m scripts.run_router '{"command": "/story my-world"}'

# Scheduler, dashboard
python -m scripts.run_scheduler --config schedule_config.yaml --once
python -m scripts.dashboard --port 8080           # endpoints: /metrics, /runs, /routing, /health
python -m scripts.tune_router --db ai_swarm.db     # analyze routing decisions, suggest thresholds

# Fleet provisioner (deploy models to hardware nodes)
python -m scripts.provision_fleet --config config/fleet_config.yaml -v

# Claude Premium Bridge (file-based task automation)
python -m scripts.bootstrap_automation -v
python -m automation.automation_cli submit <task.md>
python -m automation.watcher --config automation/config.yaml

# Tests
pytest                                        # all (~804 tests)
pytest tests/unit/                            # unit only
pytest tests/integration/                     # integration only
pytest tests/<file>::<TestClass>::<test_name>  # single test
```

## Architecture

### Core Components

1. **Graph Runner / Orchestrator** (`core/orchestrator.py`): Executes YAML graph definitions, manages run state as a dict persisted between nodes, enforces budgets. Supports state checkpointing and resume from last successful node. Accepts optional `router: ModelRouter` for per-node model selection (backward compatible with `model_call`).

2. **Agent Runtime** (`agents/`): 21 agent files. Each produces `delta_state: dict` merged into run state. Base class in `agents/base_agent.py` defines `AgentPolicy` (Pydantic) with `preferred_tier`, `min_tier`, `max_tokens_by_tier`, `allowed_local_models`, `allowed_frontier_models`, `confidence_threshold`, `required_citations`.

3. **Tiered Router** (`core/command_registry.py`, `core/tiered_dispatch.py`, `core/routing.py`, `core/provider_registry.py`): Four-tier dispatch chain. See "Tiered Routing System" below.

4. **Data Layer** (`data/`): SQLite + filesystem. 12 DAOs: `dao_sources`, `dao_entities`, `dao_claims`, `dao_metrics`, `dao_snapshots`, `dao_runs`, `dao_telemetry`, `dao_routing`, `dao_story_worlds`, `dao_threads`, `dao_episodes`, `dao_characters`. Schema in `data/schema.sql`.

5. **Model Adapters** (`core/adapters.py`): `OllamaAdapter`, `AnthropicAdapter`, `OpenAIAdapter`, `DGXSparkAdapter`. Factory: `make_model_call(mode)` where mode is `stub|tier1|tier2|ollama|ollama:<model>|anthropic|anthropic:<model>`. `make_router_from_config(path)` builds a full `ModelRouter` from `router_config.yaml`. Both `OllamaAdapter` and `AnthropicAdapter` track `total_input_tokens`, `total_output_tokens`, `call_count`. `AnthropicAdapter` supports `min_interval` rate limiting (seconds between calls).

6. **Claude Premium Bridge** (`automation/`): File-based task queue between external orchestrator and Claude Code. See "Automation System" below.

### Four Graph Loops (YAML in `graphs/`)

- **Certification** (`cert_graph.yaml`): blueprint_ingest → objective_graph → grounding_sweep → claim_extraction → lesson_composition → question_generation → qa_validation → snapshot → publish
- **Dossier** (`dossier_graph.yaml`): topic_ingest → normalize → entity_resolution → claim_extraction → metric_extraction → contradiction_check → snapshot → synthesis → publish
- **Lab** (`lab_graph.yaml`): suite_assembly → benchmark_run → scoring → trend_metrics → routing_recommendation → snapshot → publish
- **Story** (`story_graph.yaml`): world_memory_load → premise → plot → scene_writing → canon_update → contradiction_check → audience_check → qa_validation → snapshot → narration → publish (11 nodes, 32k token budget)

Each graph node specifies: `agent`, `inputs`/`outputs` (state keys), `next`, `on_fail`, `retry` policy, optional `budget` cap.

### Agent Contract

Every agent file defines: `AGENT_ID`, `VERSION`, `SYSTEM_PROMPT`, `USER_TEMPLATE`, `INPUT_SCHEMA` (Pydantic), `OUTPUT_SCHEMA`, `POLICY` (AgentPolicy), `parse(response) -> dict`, `validate(output) -> None/raise`. Agents output JSON only. `BaseAgent.run()` has a three-tier JSON recovery pipeline: (1) `repair_json()` programmatic fix for unescaped quotes/newlines and truncated output, (2) same-model LLM recovery with schema, (3) repair prompt retry loop.

Agent tier assignments (in `POLICY.preferred_tier`):
- **Tier 0** (deterministic, no LLM): qa_validator, delta, publisher, story_memory_loader
- **Tier 1** (micro LLM, 128 tokens): ingestor, normalizer, entity_resolver
- **Tier 2** (light LLM, 1024 tokens): contradiction, synthesizer, narration_formatter, and all remaining agents by default

### Tiered Routing System

Config: `config/router_config.yaml`. Implementation status tracked in `docs/router_escalation_chain_todos.md`.

**Tier 0 — Deterministic Regex** (`core/command_registry.py`):
- `CommandRegistry` matches slash commands (`/cert`, `/dossier`, `/story`, `/lab`, `/status`, `/help`) and JSON payloads
- Returns `CommandMatch` with confidence=1.0, no LLM call needed

**Tier 1 — Micro LLM** (`agents/micro_router_agent.py`, `core/tiered_dispatch.py`):
- Uses `deepseek-r1:1.5b` with 2048 ctx, 128 max tokens, temp=0
- Classifies intent, outputs `complexity_score`, `confidence`, `recommended_tier`, `safety_flag`, `safety_reason`
- Safety bypass: if `safety_flag=true`, returns `rejected` immediately without proceeding to higher tiers
- Escalates to Tier 2 if confidence < 0.75 or recommended_tier > 1

**Tier 2 — Light Reasoner** (`core/tiered_dispatch.py`):
- Uses `deepseek-r1:1.5b` with 4096 ctx, 1024 max tokens, temp=0.2
- Evaluates `quality_score` and `escalate` flag
- Returns result if quality >= 0.70, otherwise returns `needs_escalation` (tier=-1)

**Tier 3 — Frontier Pool** (`core/provider_registry.py`):
- `ProviderRegistry` with strategy-based selection: `cheapest_qualified`, `highest_quality`, `prefer_local`
- Daily cap enforcement (`daily_frontier_cap: 100`)
- Provider fallback chain: mark unavailable → try next
- `load_providers_from_config()` maps `ProviderConfig` to adapter instances
- Providers: dgx_spark (llama3:70b, local), anthropic_claude (Claude Sonnet), openai_gpt4 (GPT-4o)

**Routing score formula** (`core/routing.py:compute_routing_score`):
`score = (complexity * 0.4) + ((1 - confidence) * 0.3) + (hallucination_risk * 0.3)`

**Orchestrator integration**: `execute_graph()` accepts `router: ModelRouter` param. `_execute_node()` injects `state["_current_agent_id"]` then calls `router.select_model(agent.POLICY, state)` for per-node model selection. Logs routing decisions to `routing_decisions` DB table and `MetricsCollector`. Catches `RoutingFailure` error. Falls back to `model_call` if no router.

**Safety and hardening** (`core/tiered_dispatch.py`, `core/gpu_monitor.py`):
- Input sanitization: max length enforcement (10k default), prompt injection detection (5 regex patterns)
- Per-tier timeouts: Tier 1 = 5s, Tier 2 = 30s, enforced via `concurrent.futures.ThreadPoolExecutor`
- Concurrency control: per-tier semaphores (Tier 1 = 8, Tier 2 = 4)
- GPU health monitoring: `check_nvidia_smi()` for VRAM, `check_ollama()` for model listing, `run_health_check()` updates provider availability

### Hardware Fleet

Config: `config/fleet_config.yaml`. Provisioner: `scripts/provision_fleet.py`.

| Node | GPU | VRAM | Host |
|---|---|---|---|
| desktop-rtx4070 | RTX 4070 | 12 GB | localhost:11434 |
| mac-mini-m4 | Apple M4 | 24 GB | mac-mini.local:11434 |
| macbook-pro-m4 | Apple M4 Pro | 64 GB | macbook.local:11434 |
| dgx-spark | NVIDIA Grace Blackwell | 128 GB | spark-5034.local:11434 |

Custom models deployed to all nodes:
- `deepseek-r1:1.5b-tier1-micro` (ctx 2048, predict 128, temp 0)
- `deepseek-r1:1.5b-tier2-light` (ctx 4096, predict 1024, temp 0.2)

Base models auto-selected by VRAM: RTX 4070 (12 GB) gets `llama3:8b-instruct-q8_0`, larger nodes get bigger llama3:70b quantizations.

### Story Engine

World-scoped episodic fiction generation with persistent canon.

**DB tables**: `story_worlds`, `characters`, `story_threads`, `episodes` (+ shared `claims`, `entities`, `snapshots`).

**Story-specific agents**: `story_memory_loader` (loads world state from DB), `premise_architect`, `plot_architect`, `scene_writer`, `canon_updater`, `audience_compliance`, `narration_formatter`.

**Shared agents reused**: `contradiction`, `qa_validator`, `delta`, `publisher`.

**Tiered routing** (`scripts/run_story.py:StoryTieredRouter`): `--tiered` flag splits model execution by agent role. Creative agents (`premise_architect`, `plot_architect`, `scene_writer`, `narration_formatter`) route to Anthropic Haiku. Extraction agents (`canon_updater`, `contradiction`, `audience_compliance`) route to local Ollama. Tier 0 agents run deterministically. Token usage summary printed after each run. Orchestrator injects `state["_current_agent_id"]` so the router knows which agent is executing.

**Canon persistence** (`scripts/run_story.py:_persist_world_state`): After each episode, writes new claims, character updates (including arc_stage transitions), new/resolved threads, entities, snapshot, episode record back to DB.

**Character arc stages**: `introduction → development → testing → transformation → resolution` (enforced sequential in `dao_characters.py:update_arc_stage`).

### Automation System (Claude Premium Bridge)

Package: `automation/`. Config: `automation/config.yaml`. Bootstrap: `scripts/bootstrap_automation.py`.

- `config.py`: `AutomationConfig` dataclass with `PathsConfig`, `ValidationConfig`, `WatcherConfig`
- `queue.py`: `QueueState` (pending/processing/completed/failed lists) with atomic JSON persistence (write .tmp then `os.replace`)
- `task_schema.py`: Markdown task file parser/writer with structured headers (Goal, Context, Constraints, Success Criteria)
- `validator.py`: Task validation against schema requirements
- `result_writer.py`: Writes structured result files
- `processor.py`: Task processing pipeline
- `hardening.py`: Error recovery, stale task detection, retry logic
- `watcher.py`: Filesystem watcher polling for new tasks
- `automation_cli.py`: CLI for submit/status/list/retry operations
- `logging.py`: Automation-specific structured logging

### Budget System

Tracked per token in/out, wall time, and dollar cost. Enforced at per-node, per-run, and per-scope levels. Degradation at 80%: reduces max_sources, max_questions, skips deep synthesis. Hard exceed: `budget_degraded` event + human review flagged.

### Error Hierarchy (`core/errors.py`)

`SwarmError` → `GraphError`, `NodeError` → `AgentValidationError`, `MissingStateError`, `BudgetExceededError`, `ModelAPIError` (retryable flag), `RoutingFailure` (tier, tried_providers).

### Observability (`core/logging.py`)

Structured JSON logging with API key redaction. `MetricsCollector` tracks run duration, token usage, frontier rate, QA fail rate, delta magnitude, and router metrics (tier distribution, escalation rate/counts, provider distribution, cost by provider, avg latency/quality by tier). `log_node_event()` emits per-node records. Orchestrator persists routing decisions to `routing_decisions` table after each routed node. `scripts/tune_router.py` analyzes decisions for over/under-escalation and cost optimization.

### Config Files

| File | Purpose |
|---|---|
| `config/router_config.yaml` | Tier 1/2 model params, Tier 3 providers, escalation thresholds, daily cap |
| `config/fleet_config.yaml` | Hardware nodes, GPU specs, custom model definitions |
| `schedule_config.yaml` | Cron entries for scheduled graph runs |
| `automation/config.yaml` | Automation directory paths, validation, watcher interval |

## Key Design Rules

- Every published statement must trace back to citations (auditable provenance).
- Synthesis agents may only reference claims, metrics, and delta reports provided to them.
- Published artifacts go only in `publish/out/` (gitignored).
- API keys stored in env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OLLAMA_HOST`, `OLLAMA_MODEL`), never in repo.
- v0 targets static site + JSON artifacts; no heavy UI.
- Agent `POLICY.preferred_tier` determines default routing; orchestrator respects it unless escalation is triggered.
- Automation queue transitions are atomic — write .tmp then rename.

## Implementation Status

Tracked in `docs/` markdown files:
- `docs/router_escalation_chain_todos.md` — R0-R6 all complete
- `docs/claude_premium_bridge_todos.md` — B0-B6 all complete

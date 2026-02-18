# Tiered Local Inference Router — Phased Implementation Plan

All items below are derived from `docs/router_escalation_chain.md`. Each phase is ordered by dependency — complete earlier phases before starting later ones.

Set the checkbox to [~] while you are working on it, and to [X] when complete.

**Key design decisions:**
- Router operates at **two layers**: Tier 0 regex dispatches requests to graphs/tools; Tiers 1-3 select model per-node inside the orchestrator.
- **Tier 1 and Tier 2 are both `deepseek-r1:1.5b`**, same model, different configurations:
  - Tier 1 (Micro Router): small context (2k), max_tokens 128, temperature 0 — fast structured classification.
  - Tier 2 (Light Reasoner): larger context (4k), max_tokens 512–1024, temperature 0.2 — short reasoning and synthesis.
- **Tier 3 is a multi-provider frontier pool**, not a single model. The router selects the best provider for each request based on quality requirements and cost constraints:
  - Cloud APIs: Anthropic Claude, OpenAI GPT-4, Google Gemini, etc.
  - Local high-end hardware: NVIDIA DGX Spark (Grace Blackwell, 128GB unified memory — can run 70B+ models locally)
  - Other local Ollama models on workstation GPU
- Extends existing `core/routing.py` (`ModelRouter`, `EscalationCriteria`, `RoutingDecision`).

---

## Phase R0: Adapter Registry and Model Tiers

Extend the data layer and adapter infrastructure to support multiple named model instances and multi-provider routing. No routing logic changes yet.

### R0.1 Adapter Registry

- [X] Extend `OllamaAdapter` with configurable `max_tokens` and `context_length` fields
- [X] Add tier-specific factory functions to `core/adapters.py`:
  - `make_micro_adapter()` → `deepseek-r1:1.5b`, context 2k, max_tokens 128, temperature 0
  - `make_light_adapter()` → `deepseek-r1:1.5b`, context 4k, max_tokens 1024, temperature 0.2
- [X] Update `ModelRouter.register_local()` / `register_frontier()` to accept tier labels (e.g., `"micro"`, `"light"`, `"frontier"`) — adapters keyed by `adapter.name` (e.g. `"micro"`, `"light"`)
- [X] Add `ModelRouter.get_adapter(tier: str) -> ModelAdapter` method for tier-based lookup — implemented as `get_model_callable(decision)` which looks up by adapter name
- [X] Add a `RouterConfig` dataclass to hold tier-to-model mappings, loadable from YAML

### R0.2 Multi-Provider Adapter Framework

- [X] Define `ProviderAdapter` protocol in `core/adapters.py` — implemented as `ModelAdapter` protocol with `name`, `call(system_prompt, user_message) -> str`
  - `name: str`, `provider: str`, `call(system_prompt, user_message) -> str`
  - `cost_per_input_token: float`, `cost_per_output_token: float`
  - `quality_tier: str` (e.g., `"standard"`, `"high"`, `"frontier"`)
  - `max_context: int`, `supports_json_mode: bool`
- [X] Implement `AnthropicAdapter` — Claude API via `anthropic` SDK:
  - Config: model name, API key (env var `ANTHROPIC_API_KEY`), max_tokens, temperature
  - Maps to `messages.create()` with system prompt and user message
- [X] Implement `OpenAIAdapter` — OpenAI/compatible API via `openai` SDK:
  - Config: model name, API key (env var `OPENAI_API_KEY`), base_url (for compatible providers), max_tokens, temperature
  - Maps to `chat.completions.create()` with system + user messages
- [X] Implement `DGXSparkAdapter` — Ollama or vLLM running on DGX Spark:
  - Config: host (e.g., `http://dgx-spark:11434`), model name (e.g., `llama3:70b`), max_tokens, temperature
  - Same HTTP interface as `OllamaAdapter` but targeting remote DGX Spark hardware
  - Tracks cost as amortized local hardware cost (configurable $/token)

### R0.3 Provider Cost and Quality Registry

- [X] Implement `core/provider_registry.py`:
  - `ProviderEntry` dataclass: `name: str`, `adapter: ProviderAdapter`, `cost_per_1k_input: float`, `cost_per_1k_output: float`, `quality_score: float` (0–1 benchmark rating), `max_context: int`, `available: bool`, `tags: list[str]` (e.g., `["cloud", "local", "dgx"]`)
  - `ProviderRegistry` class: register providers, query by capability, sort by cost or quality
  - `select_provider(requirements) -> ProviderEntry`: pick best provider given task requirements
    - `requirements`: min_quality, max_cost, min_context, preferred_tags

### R0.4 Router Configuration File

- [X] Create `config/router_config.yaml`:
  - Tier 0: regex patterns and their target actions
  - Tier 1: model (`deepseek-r1:1.5b`), context 2k, max_tokens 128, temperature 0, concurrency 8+
  - Tier 2: model (`deepseek-r1:1.5b`), context 4k, max_tokens 1024, temperature 0.2, concurrency 2–4
  - Tier 3 providers (list):
    - `dgx_spark`: host, model, cost_per_1k, quality_score, tags: [local, dgx]
    - `anthropic_claude`: model, cost_per_1k, quality_score, tags: [cloud, frontier]
    - `openai_gpt4`: model, cost_per_1k, quality_score, tags: [cloud, frontier]
    - `ollama_large`: host, model, cost_per_1k, quality_score, tags: [local]
  - Escalation thresholds: confidence, complexity, reasoning_depth
  - Cost weights for composite routing score
  - Provider selection strategy: `"cheapest_qualified"` | `"highest_quality"` | `"prefer_local"`
- [X] Add `load_router_config(path) -> RouterConfig` to `core/routing.py`
- [X] Wire `RouterConfig` into `ModelRouter.__init__()` as optional config source

### R0.5 Routing Telemetry Schema

- [X] Add `routing_decisions` table to `data/schema.sql`:
  - `decision_id TEXT PK, run_id TEXT, node_id TEXT, agent_id TEXT, request_tier INTEGER, chosen_tier INTEGER, provider TEXT, escalation_reason TEXT, confidence REAL, complexity_score REAL, quality_score REAL, latency_ms REAL, tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, created_at TEXT`
- [X] Implement `data/dao_routing.py` — CRUD for routing_decisions:
  - `insert_routing_decision()`, `get_decisions_for_run()`, `get_tier_distribution()`, `get_cost_by_provider()`

### R0.6 Phase R0 Tests

- [X] Test adapter factory functions create correct configs for Tier 1 and Tier 2 (same model, different settings)
- [X] Test `ModelRouter` registration with tier labels and lookup
- [X] Test `ProviderRegistry` registration and `select_provider()` with quality/cost filters
- [X] Test provider selection strategies: cheapest_qualified, highest_quality, prefer_local
- [X] Test `load_router_config()` parses YAML correctly including provider list
- [X] Test routing_decisions DAO round-trip
- [X] Test adapter connectivity (Ollama health check for `deepseek-r1:1.5b`)
- [X] Test `DGXSparkAdapter` falls back gracefully when DGX Spark is unreachable

---

## Phase R1: Tier 0 — Deterministic Regex Layer

Build the regex/command dispatch layer that handles requests without any LLM call.

### R1.1 Command Registry

- [X] Implement `core/command_registry.py`:
  - `CommandPattern` dataclass: `pattern: str (regex)`, `action: str`, `target: str`, `description: str`
  - `CommandRegistry` class: register patterns, match against input, return `CommandMatch` or None
  - `CommandMatch` dataclass: `action: str`, `target: str`, `args: dict`, `confidence: float (1.0 for regex)`
- [X] Register default command patterns:
  - `/cert <id>` → `execute_graph`, target `run_cert.py`
  - `/dossier <id>` → `execute_graph`, target `run_dossier.py`
  - `/story <world_id>` → `execute_graph`, target `run_story.py`
  - `/lab <suite_id>` → `execute_graph`, target `run_lab.py`
  - `/status` → `show_status`
  - `/help` → `show_help`
- [X] Support JSON payload detection: if input parses as JSON with a `"command"` key, route deterministically

### R1.2 Tier 0 Integration

- [X] Implement `core/tiered_dispatch.py`:
  - `TieredDispatcher` class: holds `CommandRegistry` + `ModelRouter` + `ProviderRegistry`
  - `dispatch(request: str) -> DispatchResult` method:
    1. Try Tier 0 (regex match) — if match, return `DispatchResult(tier=0, ...)`
    2. Else pass to Tier 1
  - `DispatchResult` dataclass: `tier: int`, `action: str`, `target: str`, `args: dict`, `confidence: float`, `provider: str | None`, `model_response: str | None`

### R1.3 CLI Entrypoint

- [X] Create `scripts/run_router.py` — unified CLI entrypoint:
  - Accepts free-form text or slash commands
  - Routes through `TieredDispatcher`
  - Executes the resolved action (graph run, tool call, etc.)
  - Logs routing decision to DB

### R1.4 Phase R1 Tests

- [X] Test regex matching for all registered command patterns
- [X] Test JSON payload routing
- [X] Test unknown input falls through to Tier 1
- [X] Test `DispatchResult` structure for Tier 0 matches
- [X] Test slash command argument parsing (e.g., `/cert az-104` extracts cert_id)

---

## Phase R2: Tier 1 — Micro LLM Router (deepseek-r1:1.5b, small config)

Wire Instance A (`deepseek-r1:1.5b` with small context/tokens) for intent classification and tool selection.

### R2.1 Micro Router Agent

- [X] Implement `agents/micro_router_agent.py`:
  - SYSTEM_PROMPT: classify intent, estimate complexity, select tool/graph, output structured JSON
  - USER_TEMPLATE: `{request_text}`, `{available_actions}`, `{available_graphs}`
  - Output schema: `intent: str`, `requires_reasoning: bool`, `complexity_score: float`, `confidence: float`, `recommended_tier: int (1|2|3)`, `action: str`, `target: str`
  - Validation: confidence in [0,1], complexity_score in [0,1], recommended_tier in {1,2,3}
  - POLICY: `preferred_tier=1`, max_tokens 128, context 2k

### R2.2 Tier 1 Integration

- [X] Extend `TieredDispatcher.dispatch()` with Tier 1 step:
  - Call `micro_router_agent` via Tier 1 adapter (deepseek-r1:1.5b, small config)
  - If `recommended_tier == 1` and `confidence >= 0.75`: execute action directly
  - If `recommended_tier >= 2` or `confidence < 0.75`: pass to Tier 2
  - If structured validation fails twice: escalate to Tier 2
- [X] Add `_tier1_classify()` method to `TieredDispatcher`

### R2.3 Composite Routing Score

- [X] Implement `compute_routing_score()` in `core/routing.py`:
  - `routing_score = (complexity_score * w1) + ((1 - confidence) * w2) + (hallucination_risk * w3)`
  - Default weights from `RouterConfig`
  - Escalate when `routing_score > threshold`
- [X] Wire composite score into `TieredDispatcher` escalation logic

### R2.4 Phase R2 Tests

- [X] Test micro_router_agent parse/validate with sample responses
- [X] Test Tier 1 classification routes simple commands without escalation
- [X] Test Tier 1 escalation on low confidence (< 0.75)
- [X] Test Tier 1 escalation on high complexity (> 0.35)
- [X] Test composite routing score calculation
- [X] Test structured validation failure triggers escalation after 2 retries

---

## Phase R3: Tier 2 — Light LLM Reasoner (deepseek-r1:1.5b, large config)

Wire Instance B (`deepseek-r1:1.5b` with larger context/tokens) for short reasoning tasks. Also integrate per-node model selection into the orchestrator.

### R3.1 Per-Node Model Selection in Orchestrator

- [X] Update `_execute_node()` in `core/orchestrator.py`:
  - Before agent execution, call `ModelRouter.select_model(agent.POLICY, state)`
  - Get callable via `ModelRouter.get_model_callable(decision)`
  - Pass selected callable as `model_call` to `agent.run()`
  - Log routing decision (tier, model, reason) to run events
- [X] Add `router: ModelRouter` parameter to `execute_graph()` — kept `model_call`/`frontier_model_call` for backward compatibility
- [X] Backward compatibility: if `model_call` is provided and no router, use it directly (existing behavior)

### R3.2 Agent Policy Tier Mapping

- [X] Update `AgentPolicy` in `agents/base_agent.py`:
  - Add `preferred_tier: int = 2` field (default tier for this agent)
  - Add `min_tier: int = 1` field (lowest tier that can handle this agent)
  - Add `max_tokens_by_tier: dict[int, int] = {}` for tier-specific token limits
- [X] Update all existing agents with appropriate tier preferences:
  - Deterministic agents (qa_validator, delta, publisher, story_memory_loader): `preferred_tier=0`
  - Classification agents (ingestor, normalizer, entity_resolver): `preferred_tier=1`
  - Extraction/synthesis agents (claim_extractor, scene_writer, etc.): `preferred_tier=2` (default)
  - Complex reasoning (contradiction, synthesis, narration_formatter): `preferred_tier=2`, escalation to 3

### R3.3 Tier 2 Dispatch

- [X] Extend `TieredDispatcher.dispatch()` with Tier 2 step:
  - Call light model (deepseek-r1:1.5b, large config) with the request + Tier 1 classification context
  - Evaluate output: `reasoning_depth_estimate`, `quality_score`, `confidence`
  - If `quality_score >= threshold` and `escalate == false`: return result
  - Else escalate to Tier 3
- [X] Add `_tier2_reason()` method to `TieredDispatcher`

### R3.4 Escalation Signal Injection

- [X] Update agents to inject escalation signals into state after execution — `ModelRouter._evaluate_escalation()` already reads these from state:
  - `_last_confidence` — from agent's parse confidence
  - `_missing_citations_count` — from QA violations
  - `_contradiction_ambiguity` — from contradiction agent output
  - `_synthesis_complexity` — from synthesis/scene_writer complexity estimate
- [X] Wire `EscalationCriteria` evaluation into per-node routing decision — done in `_execute_node()` via `router.select_model()`

### R3.5 Phase R3 Tests

- [X] Test orchestrator per-node model selection uses router
- [X] Test agent preferred_tier is respected in routing
- [X] Test Tier 1 and Tier 2 use same model (`deepseek-r1:1.5b`) with different configs
- [X] Test escalation from Tier 2 to Tier 3 on low quality_score
- [X] Test escalation from Tier 2 to Tier 3 on high reasoning_depth
- [X] Test escalation signal injection from agents into state
- [X] Test backward compatibility: graph execution with plain model_call still works
- [X] Integration test: full cert graph with tiered routing (mock models)

---

## Phase R4: Tier 3 — Multi-Provider Frontier Pool

Wire the frontier pool with quality/cost-based provider selection. Tier 3 selects the best available provider for each request rather than using a single model.

### R4.1 Provider Adapters

- [X] Implement and register all Tier 3 provider adapters — done in R0.2:
  - `DGXSparkAdapter` — local DGX Spark (Grace Blackwell, 128GB unified memory) running large models via Ollama/vLLM
  - `AnthropicAdapter` — Claude API (Sonnet, Opus)
  - `OpenAIAdapter` — GPT-4o, GPT-4-turbo (also supports compatible endpoints)
  - `OllamaAdapter` (existing) — any additional local Ollama models on workstation GPU
- [X] Register all providers in `ProviderRegistry` with cost/quality metadata from `router_config.yaml` — `load_providers_from_config()` wires config entries to adapters
- [X] Add `--router-config` flag to all CLI scripts (run_cert, run_dossier, run_lab, run_story) — when provided, calls `make_router_from_config(path)` and passes `router=` to `execute_graph()` instead of `model_call=`
- [X] Add `make_router_from_config(config_path)` to `core/adapters.py` — builds `ModelRouter` with tier 1/2 local adapters and tier 3 providers from YAML config
- [X] Add `"anthropic"` and `"anthropic:<model>"` modes to `make_model_call()` in `core/adapters.py`

### R4.2 Quality/Cost-Based Provider Selection

- [X] Implement provider selection logic in `ProviderRegistry.select_provider()` — done in R0.3:
  - Input: `TaskRequirements` dataclass — `min_quality: float`, `max_cost_per_1k: float`, `min_context: int`, `preferred_tags: list[str]`, `required_capabilities: list[str]`
  - Selection strategies (configurable in `RouterConfig`):
    - `cheapest_qualified` — filter by min_quality, sort by cost ascending
    - `highest_quality` — filter by max_cost, sort by quality descending
    - `prefer_local` — prioritize `local`/`dgx` tagged providers, then sort by quality
  - Availability check: ping provider before selection, skip unavailable
- [X] Wire provider selection into `ModelRouter`: `select_provider_with_fallback()` provides strategy-based selection with fallback
- [X] Log selected provider name and cost to routing decision — routing event includes provider info

### R4.3 Frontier Escalation Rules

- [X] Implement Tier 3 escalation criteria in `TieredDispatcher` — Tier 2 `_tier2_reason()` escalates based on quality_score, reasoning_depth, and escalate flag:
  - `reasoning_depth_estimate > 3`
  - `quality_score < threshold` (configurable)
  - Long context (> 4k tokens)
  - Multi-document synthesis
  - User-requested high precision (flag in state)
- [X] Add daily frontier usage cap: `max_frontier_calls_per_day` in RouterConfig (per-provider and aggregate) — `daily_frontier_cap` field exists in `RouterConfig`
- [X] Implement cap enforcement in `ProviderRegistry`: `is_cap_exceeded()`, `record_call()`, `select_provider_with_fallback()` handles cap + fallback

### R4.4 Failure Handling Chain

- [X] Implement retry-then-escalate in `TieredDispatcher`:
  - Tier 1 fails → retry (DEFAULT_MAX_TIER1_RETRIES) → escalate to Tier 2
  - Tier 2 fails → escalate to Tier 3 (needs_escalation)
  - Tier 3 fails with selected provider → `select_provider_with_fallback()` tries next
  - All providers fail → `RoutingFailure` error
- [X] Add `RoutingFailure` error type to `core/errors.py`
- [X] Update orchestrator to catch `RoutingFailure` and emit appropriate event

### R4.5 Phase R4 Tests

- [X] Test `AnthropicAdapter` call structure (mock HTTP) — in `test_adapters_extended.py`
- [X] Test `OpenAIAdapter` call structure (mock HTTP) — in `test_adapters_extended.py`
- [X] Test `DGXSparkAdapter` with remote Ollama host — in `test_adapters_extended.py`
- [X] Test provider selection: cheapest_qualified strategy — in `test_provider_registry.py`
- [X] Test provider selection: highest_quality strategy — in `test_provider_registry.py`
- [X] Test provider selection: prefer_local prioritizes DGX Spark and local Ollama — in `test_provider_registry.py`
- [X] Test provider fallback when first choice is unavailable
- [X] Test daily frontier cap enforcement (allow, then deny, then fallback)
- [X] Test full escalation chain: Tier 1 → Tier 2 → Tier 3 (provider pool)
- [X] Test Tier 3 provider failover (first provider fails → try next)
- [X] Test all Tier 3 providers fail → structured error
- [X] Integration test: graph run with all tiers active (mock models at each tier)

### R4.6 Story Engine Tiered Routing

Per-agent model split for the story graph — creative agents on Anthropic Haiku, extraction agents on local Ollama, tier 0 agents deterministic (no LLM).

- [X] Add `StoryTieredRouter(ModelRouter)` in `scripts/run_story.py`:
  - Routes by `state["_current_agent_id"]` (injected by orchestrator)
  - Creative agents (`premise_architect`, `plot_architect`, `scene_writer`, `narration_formatter`) → Anthropic Haiku (frontier)
  - Extraction agents (`canon_updater`, `contradiction`, `audience_compliance`) → local Ollama llama3:8b (local)
  - Tier 0 agents (`story_memory_loader`, `qa_validator`, `delta`, `publisher`) → deterministic, no LLM
- [X] Add `--tiered` CLI flag to `scripts/run_story.py`
- [X] Inject `state["_current_agent_id"] = agent.AGENT_ID` in `core/orchestrator.py:_execute_node()` before router block
- [X] Add token tracking to `OllamaAdapter` and `AnthropicAdapter` (`total_input_tokens`, `total_output_tokens`, `call_count`)
  - Ollama: reads `prompt_eval_count` / `eval_count` from response
  - Anthropic: reads `usage.input_tokens` / `usage.output_tokens` from response
- [X] Add per-adapter token usage summary printed after run
- [X] Add `min_interval` rate limiter to `AnthropicAdapter` (configurable seconds between calls, default 0)
- [X] Add `repair_json()` state-machine in `agents/base_agent.py`:
  - Single-pass fix for unescaped quotes (dialogue in prose), literal newlines/tabs/carriage-returns inside JSON strings
  - Heuristic: `"` inside a string is structural (closes the string) only if next non-whitespace char is `:` `,` `}` `]`
  - Truncation repair: detects and closes missing brackets/braces at EOF (for output that hits `max_tokens`)
  - Wired into `BaseAgent.run()` as first recovery step before LLM-based JSON recovery
- [X] Update `BaseAgent._try_json_recovery()` to use same model (via `model_call`) instead of separate 1.5b adapter
- [X] Update `scene_writer_agent.py`: `parse()` computes `episode_text` from scenes when missing (avoids requiring duplicate output that doubles token cost)
- [X] End-to-end verified: full 11-node story graph completes with tiered routing (4 Haiku calls, 3 Ollama calls, 0 retries)

---

## Phase R5: Observability and Tuning

Logging, metrics, and threshold tuning for the tiered router.

### R5.1 Routing Telemetry

- [X] Log every routing decision to `routing_decisions` table — orchestrator `_execute_node()` now calls `insert_routing_decision()` after each routed node execution:
  - Request tier, chosen tier, provider name, escalation reason, latency, created_at
  - DB persistence is best-effort (caught exceptions don't break execution)
- [X] Add `_log_routing_decision()` helper to `TieredDispatcher` — logs tier, provider, latency, quality to MetricsCollector after every dispatch
- [X] Extend `MetricsCollector` in `core/logging.py` with router metrics via `record_routing_decision()`:
  - `tier_distribution`: count of requests per tier
  - `escalation_rate`: fraction of routing decisions that were escalated
  - `frontier_usage_rate`: fraction of requests reaching frontier (existing)
  - `provider_distribution`: count of requests per provider
  - `cost_by_provider`: total cost broken down by provider
  - `avg_latency_by_tier`: average latency per tier
  - `avg_quality_by_tier`: average quality score per tier

### R5.2 Dashboard Integration

- [X] Add `/routing` endpoint to `scripts/dashboard.py`:
  - In-memory metrics: tier distribution, escalation rate/counts, provider distribution, cost by provider, avg latency/quality by tier
  - DB metrics: tier distribution and cost by provider from `routing_decisions` table
  - Optional `?run_id=` query param to filter by run
  - Per-run decision detail list

### R5.3 Threshold Tuning

- [X] Add `scripts/tune_router.py` — analyze routing_decisions and suggest threshold adjustments:
  - `analyze_over_escalation()`: high-confidence requests sent to higher tiers
  - `analyze_under_escalation()`: low-quality results from lower tiers
  - `analyze_cost_optimization()`: per-provider total cost, avg cost/call, avg latency
  - `suggest_thresholds()`: recommended confidence and quality thresholds based on averages
  - Supports `--json` output and `--run-id` filter
- [X] Support `RouterConfig` hot-reload (re-read YAML without restart):
  - `ModelRouter.reload_config(path)`: updates `escalation_criteria` and `config` from YAML, preserves adapters
  - `TieredDispatcher.reload_config(path)`: updates confidence/quality thresholds, per-tier timeouts, concurrency semaphores, and propagates to attached `ModelRouter`

### R5.4 Phase R5 Tests

- [X] Test routing decision logging to DB with provider field — `TestRoutingDecisionDB` (4 tests)
- [X] Test MetricsCollector router metrics including provider breakdown — `TestMetricsCollectorRouter` (7 tests)
- [X] Test threshold tuning script with synthetic data — `TestTuneRouter` (6 tests)
- [X] Test config hot-reload changes thresholds — `TestModelRouterReload` (2 tests), `TestDispatcherReload` (2 tests), `TestMakeRouterFromConfig` (1 test)

---

## Phase R6: Safety and Hardening

Reliability, safety rails, and production hardening.

### R6.1 Safety Rails

- [X] Add safety classification to micro router output: `safety_flag: bool`, `safety_reason: str` — added to `MicroRouterOutput` schema, parse, and system prompt
- [X] If safety_flag is true: bypass reasoning tiers, return `DispatchResult(action="rejected", safety_flagged=True)` immediately from `_tier1_classify()`
- [X] Add input sanitization in `TieredDispatcher`:
  - `sanitize_input()`: enforces `max_input_length` (default 10k chars)
  - `detect_injection()`: static method checks 5 regex patterns (ignore instructions, disregard prior, you are now, system: prefix, system tags)
  - Rejection at dispatch entry point before any LLM call

### R6.2 Timeout Enforcement

- [X] Per-tier timeout defaults: Tier 1 = 5s, Tier 2 = 30s (`DEFAULT_TIER1_TIMEOUT`, `DEFAULT_TIER2_TIMEOUT`)
- [X] `TierConfig` extended with `timeout: float = 30.0` field
- [X] Enforce via `_call_with_timeout()` using `concurrent.futures.ThreadPoolExecutor` with `future.result(timeout=...)`
  - Tier 1: wraps `agent.run()` call in `_tier1_classify()`
  - Tier 2: wraps `self.tier2_model_call()` in `_tier2_reason()`
- [X] On timeout: catches `TimeoutError`/`concurrent.futures.TimeoutError`, logs warning, escalates to next tier

### R6.3 Concurrency Control

- [X] Semaphore-based concurrency limits per tier in `TieredDispatcher`:
  - Tier 1: `threading.Semaphore(8)` — high concurrency for micro classification
  - Tier 2: `threading.Semaphore(4)` — moderate for light reasoning
- [X] `_acquire_semaphore(tier, timeout)` / `_release_semaphore(tier)` helpers
- [X] Dispatch acquires semaphore before tier call, releases in `finally` block
- [X] If semaphore not acquired within timeout, tier is skipped (escalates to next)

### R6.4 GPU and Hardware Health Monitoring

- [X] Added `core/gpu_monitor.py`:
  - `check_nvidia_smi()`: parses `nvidia-smi --query-gpu` CSV output → `GPUStatus` dataclass (name, VRAM total/used/free, utilization, temperature, `healthy` property at <90% VRAM)
  - `check_ollama(host)`: GET `/api/tags` → `OllamaHealth` (reachable, loaded_models, error)
  - `check_health()`: aggregate → `HealthReport` with `local_gpu_healthy`, `local_ollama_reachable`, `dgx_spark_reachable` properties
- [X] Integrated into `TieredDispatcher.run_health_check()`:
  - If DGX Spark unreachable: marks dgx providers unavailable in `ProviderRegistry`
  - If DGX Spark recovers: marks dgx providers available again
  - Non-dgx providers unaffected
  - GPU VRAM pressure logged as warning

### R6.5 Phase R6 Tests

- [X] Test safety flag detection and bypass — `TestSafetyFlagBypass` (2 tests)
- [X] Test input sanitization — `TestInputSanitization` (7 tests), `TestStaticDetectInjection` (3 tests)
- [X] Test per-tier timeout enforcement — `TestTimeoutEnforcement` (3 tests)
- [X] Test concurrency semaphore limits — `TestConcurrencyControl` (3 tests)
- [X] Test GPU health check parsing (local) — `TestNvidiaSmi` (3 tests), `TestGPUStatus` (3 tests)
- [X] Test DGX Spark / Ollama health check (mock HTTP) — `TestOllamaHealth` (3 tests)
- [X] Test provider availability tracking (mark down, mark up) — `TestProviderAvailabilityTracking` (3 tests)
- [X] Test health report properties — `TestHealthReport` (2 tests)

---

## Open Decisions

| Decision | Default | Notes |
|----------|---------|-------|
| Tier 1 model | `deepseek-r1:1.5b` Q4, ctx 2k, max 128 tok | Fast classification instance |
| Tier 2 model | `deepseek-r1:1.5b` Q4/Q5, ctx 4k, max 1024 tok | Same model, larger config for reasoning |
| Tier 3 provider selection strategy | `prefer_local` | Prioritize DGX Spark and local Ollama, then cloud APIs |
| DGX Spark model | TBD (70B+ class) | Depends on what's loaded; Grace Blackwell can handle large models |
| Cloud providers | Anthropic Claude, OpenAI GPT-4 | Add more as needed; config-driven |
| Confidence threshold (Tier 1 → 2) | 0.75 | Tune based on routing telemetry |
| Complexity threshold (Tier 1 → 2) | 0.35 | Tune based on routing telemetry |
| Quality threshold (Tier 2 → 3) | 0.70 | Tune based on output quality metrics |
| Daily frontier cap | 100 calls aggregate, per-provider limits configurable | Prevent runaway spend |
| Composite score weights | w1=0.4, w2=0.3, w3=0.3 | complexity, inverse-confidence, hallucination risk |
| Provider cost tracking | Amortized $/token for local, API pricing for cloud | DGX Spark cost = electricity + amortized hardware |
| Concurrency model | Semaphore per tier + per provider | Could use async queue or thread pool instead |
| Config format | YAML | Consistent with graph definitions |

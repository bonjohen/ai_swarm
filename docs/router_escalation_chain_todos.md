# Tiered Local Inference Router — Phased Implementation Plan

All items below are derived from `docs/router_escalation_chain.md`. Each phase is ordered by dependency — complete earlier phases before starting later ones.

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

- [ ] Extend `OllamaAdapter` with configurable `max_tokens` and `context_length` fields
- [ ] Add tier-specific factory functions to `core/adapters.py`:
  - `make_micro_adapter()` → `deepseek-r1:1.5b`, context 2k, max_tokens 128, temperature 0
  - `make_light_adapter()` → `deepseek-r1:1.5b`, context 4k, max_tokens 1024, temperature 0.2
- [ ] Update `ModelRouter.register_local()` / `register_frontier()` to accept tier labels (e.g., `"micro"`, `"light"`, `"frontier"`)
- [ ] Add `ModelRouter.get_adapter(tier: str) -> ModelAdapter` method for tier-based lookup
- [ ] Add a `RouterConfig` dataclass to hold tier-to-model mappings, loadable from YAML

### R0.2 Multi-Provider Adapter Framework

- [ ] Define `ProviderAdapter` protocol in `core/adapters.py`:
  - `name: str`, `provider: str`, `call(system_prompt, user_message) -> str`
  - `cost_per_input_token: float`, `cost_per_output_token: float`
  - `quality_tier: str` (e.g., `"standard"`, `"high"`, `"frontier"`)
  - `max_context: int`, `supports_json_mode: bool`
- [ ] Implement `AnthropicAdapter` — Claude API via `anthropic` SDK:
  - Config: model name, API key (env var `ANTHROPIC_API_KEY`), max_tokens, temperature
  - Maps to `messages.create()` with system prompt and user message
- [ ] Implement `OpenAIAdapter` — OpenAI/compatible API via `openai` SDK:
  - Config: model name, API key (env var `OPENAI_API_KEY`), base_url (for compatible providers), max_tokens, temperature
  - Maps to `chat.completions.create()` with system + user messages
- [ ] Implement `DGXSparkAdapter` — Ollama or vLLM running on DGX Spark:
  - Config: host (e.g., `http://dgx-spark:11434`), model name (e.g., `llama3:70b`), max_tokens, temperature
  - Same HTTP interface as `OllamaAdapter` but targeting remote DGX Spark hardware
  - Tracks cost as amortized local hardware cost (configurable $/token)

### R0.3 Provider Cost and Quality Registry

- [ ] Implement `core/provider_registry.py`:
  - `ProviderEntry` dataclass: `name: str`, `adapter: ProviderAdapter`, `cost_per_1k_input: float`, `cost_per_1k_output: float`, `quality_score: float` (0–1 benchmark rating), `max_context: int`, `available: bool`, `tags: list[str]` (e.g., `["cloud", "local", "dgx"]`)
  - `ProviderRegistry` class: register providers, query by capability, sort by cost or quality
  - `select_provider(requirements) -> ProviderEntry`: pick best provider given task requirements
    - `requirements`: min_quality, max_cost, min_context, preferred_tags

### R0.4 Router Configuration File

- [ ] Create `config/router_config.yaml`:
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
- [ ] Add `load_router_config(path) -> RouterConfig` to `core/routing.py`
- [ ] Wire `RouterConfig` into `ModelRouter.__init__()` as optional config source

### R0.5 Routing Telemetry Schema

- [ ] Add `routing_decisions` table to `data/schema.sql`:
  - `decision_id TEXT PK, run_id TEXT, node_id TEXT, agent_id TEXT, request_tier INTEGER, chosen_tier INTEGER, provider TEXT, escalation_reason TEXT, confidence REAL, complexity_score REAL, quality_score REAL, latency_ms REAL, tokens_in INTEGER, tokens_out INTEGER, cost_usd REAL, created_at TEXT`
- [ ] Implement `data/dao_routing.py` — CRUD for routing_decisions:
  - `insert_routing_decision()`, `get_decisions_for_run()`, `get_tier_distribution()`, `get_cost_by_provider()`

### R0.6 Phase R0 Tests

- [ ] Test adapter factory functions create correct configs for Tier 1 and Tier 2 (same model, different settings)
- [ ] Test `ModelRouter` registration with tier labels and lookup
- [ ] Test `ProviderRegistry` registration and `select_provider()` with quality/cost filters
- [ ] Test provider selection strategies: cheapest_qualified, highest_quality, prefer_local
- [ ] Test `load_router_config()` parses YAML correctly including provider list
- [ ] Test routing_decisions DAO round-trip
- [ ] Test adapter connectivity (Ollama health check for `deepseek-r1:1.5b`)
- [ ] Test `DGXSparkAdapter` falls back gracefully when DGX Spark is unreachable

---

## Phase R1: Tier 0 — Deterministic Regex Layer

Build the regex/command dispatch layer that handles requests without any LLM call.

### R1.1 Command Registry

- [ ] Implement `core/command_registry.py`:
  - `CommandPattern` dataclass: `pattern: str (regex)`, `action: str`, `target: str`, `description: str`
  - `CommandRegistry` class: register patterns, match against input, return `CommandMatch` or None
  - `CommandMatch` dataclass: `action: str`, `target: str`, `args: dict`, `confidence: float (1.0 for regex)`
- [ ] Register default command patterns:
  - `/cert <id>` → `execute_graph`, target `run_cert.py`
  - `/dossier <id>` → `execute_graph`, target `run_dossier.py`
  - `/story <world_id>` → `execute_graph`, target `run_story.py`
  - `/lab <suite_id>` → `execute_graph`, target `run_lab.py`
  - `/status` → `show_status`
  - `/help` → `show_help`
- [ ] Support JSON payload detection: if input parses as JSON with a `"command"` key, route deterministically

### R1.2 Tier 0 Integration

- [ ] Implement `core/tiered_dispatch.py`:
  - `TieredDispatcher` class: holds `CommandRegistry` + `ModelRouter` + `ProviderRegistry`
  - `dispatch(request: str) -> DispatchResult` method:
    1. Try Tier 0 (regex match) — if match, return `DispatchResult(tier=0, ...)`
    2. Else pass to Tier 1
  - `DispatchResult` dataclass: `tier: int`, `action: str`, `target: str`, `args: dict`, `confidence: float`, `provider: str | None`, `model_response: str | None`

### R1.3 CLI Entrypoint

- [ ] Create `scripts/run_router.py` — unified CLI entrypoint:
  - Accepts free-form text or slash commands
  - Routes through `TieredDispatcher`
  - Executes the resolved action (graph run, tool call, etc.)
  - Logs routing decision to DB

### R1.4 Phase R1 Tests

- [ ] Test regex matching for all registered command patterns
- [ ] Test JSON payload routing
- [ ] Test unknown input falls through to Tier 1
- [ ] Test `DispatchResult` structure for Tier 0 matches
- [ ] Test slash command argument parsing (e.g., `/cert az-104` extracts cert_id)

---

## Phase R2: Tier 1 — Micro LLM Router (deepseek-r1:1.5b, small config)

Wire Instance A (`deepseek-r1:1.5b` with small context/tokens) for intent classification and tool selection.

### R2.1 Micro Router Agent

- [ ] Implement `agents/micro_router_agent.py`:
  - SYSTEM_PROMPT: classify intent, estimate complexity, select tool/graph, output structured JSON
  - USER_TEMPLATE: `{request_text}`, `{available_actions}`, `{available_graphs}`
  - Output schema: `intent: str`, `requires_reasoning: bool`, `complexity_score: float`, `confidence: float`, `recommended_tier: int (1|2|3)`, `action: str`, `target: str`
  - Validation: confidence in [0,1], complexity_score in [0,1], recommended_tier in {1,2,3}
  - POLICY: `preferred_tier=1`, max_tokens 128, context 2k

### R2.2 Tier 1 Integration

- [ ] Extend `TieredDispatcher.dispatch()` with Tier 1 step:
  - Call `micro_router_agent` via Tier 1 adapter (deepseek-r1:1.5b, small config)
  - If `recommended_tier == 1` and `confidence >= 0.75`: execute action directly
  - If `recommended_tier >= 2` or `confidence < 0.75`: pass to Tier 2
  - If structured validation fails twice: escalate to Tier 2
- [ ] Add `_tier1_classify()` method to `TieredDispatcher`

### R2.3 Composite Routing Score

- [ ] Implement `compute_routing_score()` in `core/routing.py`:
  - `routing_score = (complexity_score * w1) + ((1 - confidence) * w2) + (hallucination_risk * w3)`
  - Default weights from `RouterConfig`
  - Escalate when `routing_score > threshold`
- [ ] Wire composite score into `TieredDispatcher` escalation logic

### R2.4 Phase R2 Tests

- [ ] Test micro_router_agent parse/validate with sample responses
- [ ] Test Tier 1 classification routes simple commands without escalation
- [ ] Test Tier 1 escalation on low confidence (< 0.75)
- [ ] Test Tier 1 escalation on high complexity (> 0.35)
- [ ] Test composite routing score calculation
- [ ] Test structured validation failure triggers escalation after 2 retries

---

## Phase R3: Tier 2 — Light LLM Reasoner (deepseek-r1:1.5b, large config)

Wire Instance B (`deepseek-r1:1.5b` with larger context/tokens) for short reasoning tasks. Also integrate per-node model selection into the orchestrator.

### R3.1 Per-Node Model Selection in Orchestrator

- [ ] Update `_execute_node()` in `core/orchestrator.py`:
  - Before agent execution, call `ModelRouter.select_model(agent.POLICY, state)`
  - Get callable via `ModelRouter.get_model_callable(decision)`
  - Pass selected callable as `model_call` to `agent.run()`
  - Log routing decision (tier, model, reason) to run events
- [ ] Remove direct `model_call` / `frontier_model_call` parameter pattern from `execute_graph()` — replace with `router: ModelRouter`
- [ ] Backward compatibility: if `model_call` is provided and no router, use it directly (existing behavior)

### R3.2 Agent Policy Tier Mapping

- [ ] Update `AgentPolicy` in `agents/base_agent.py`:
  - Add `preferred_tier: int = 2` field (default tier for this agent)
  - Add `min_tier: int = 1` field (lowest tier that can handle this agent)
  - Add `max_tokens_by_tier: dict[int, int] = {}` for tier-specific token limits
- [ ] Update all existing agents with appropriate tier preferences:
  - Deterministic agents (qa_validator, delta, publisher, story_memory_loader): `preferred_tier=0`
  - Classification agents (ingestor, normalizer, entity_resolver): `preferred_tier=1`
  - Extraction/synthesis agents (claim_extractor, scene_writer, etc.): `preferred_tier=2`
  - Complex reasoning (contradiction, synthesis, narration_formatter): `preferred_tier=2`, escalation to 3

### R3.3 Tier 2 Dispatch

- [ ] Extend `TieredDispatcher.dispatch()` with Tier 2 step:
  - Call light model (deepseek-r1:1.5b, large config) with the request + Tier 1 classification context
  - Evaluate output: `reasoning_depth_estimate`, `quality_score`, `confidence`
  - If `quality_score >= threshold` and `escalate == false`: return result
  - Else escalate to Tier 3
- [ ] Add `_tier2_reason()` method to `TieredDispatcher`

### R3.4 Escalation Signal Injection

- [ ] Update agents to inject escalation signals into state after execution:
  - `_last_confidence` — from agent's parse confidence
  - `_missing_citations_count` — from QA violations
  - `_contradiction_ambiguity` — from contradiction agent output
  - `_synthesis_complexity` — from synthesis/scene_writer complexity estimate
- [ ] Wire `EscalationCriteria` evaluation into per-node routing decision

### R3.5 Phase R3 Tests

- [ ] Test orchestrator per-node model selection uses router
- [ ] Test agent preferred_tier is respected in routing
- [ ] Test Tier 1 and Tier 2 use same model (`deepseek-r1:1.5b`) with different configs
- [ ] Test escalation from Tier 2 to Tier 3 on low quality_score
- [ ] Test escalation from Tier 2 to Tier 3 on high reasoning_depth
- [ ] Test escalation signal injection from agents into state
- [ ] Test backward compatibility: graph execution with plain model_call still works
- [ ] Integration test: full cert graph with tiered routing (mock models)

---

## Phase R4: Tier 3 — Multi-Provider Frontier Pool

Wire the frontier pool with quality/cost-based provider selection. Tier 3 selects the best available provider for each request rather than using a single model.

### R4.1 Provider Adapters

- [ ] Implement and register all Tier 3 provider adapters:
  - `DGXSparkAdapter` — local DGX Spark (Grace Blackwell, 128GB unified memory) running large models via Ollama/vLLM
  - `AnthropicAdapter` — Claude API (Sonnet, Opus)
  - `OpenAIAdapter` — GPT-4o, GPT-4-turbo (also supports compatible endpoints)
  - `OllamaAdapter` (existing) — any additional local Ollama models on workstation GPU
- [ ] Register all providers in `ProviderRegistry` with cost/quality metadata from `router_config.yaml`
- [ ] Add `--router-config` flag to all CLI scripts (run_cert, run_dossier, run_lab, run_story)
- [ ] Update `make_model_call()` to support `"router"` mode that initializes all tiers from config

### R4.2 Quality/Cost-Based Provider Selection

- [ ] Implement provider selection logic in `ProviderRegistry.select_provider()`:
  - Input: `TaskRequirements` dataclass — `min_quality: float`, `max_cost_per_1k: float`, `min_context: int`, `preferred_tags: list[str]`, `required_capabilities: list[str]`
  - Selection strategies (configurable in `RouterConfig`):
    - `cheapest_qualified` — filter by min_quality, sort by cost ascending
    - `highest_quality` — filter by max_cost, sort by quality descending
    - `prefer_local` — prioritize `local`/`dgx` tagged providers, then sort by quality
  - Availability check: ping provider before selection, skip unavailable
- [ ] Wire provider selection into `ModelRouter`: when Tier 3 is selected, call `ProviderRegistry.select_provider()` to pick the specific model
- [ ] Log selected provider name and cost to routing decision

### R4.3 Frontier Escalation Rules

- [ ] Implement Tier 3 escalation criteria in `TieredDispatcher`:
  - `reasoning_depth_estimate > 3`
  - `quality_score < threshold` (configurable)
  - Long context (> 4k tokens)
  - Multi-document synthesis
  - User-requested high precision (flag in state)
- [ ] Add daily frontier usage cap: `max_frontier_calls_per_day` in RouterConfig (per-provider and aggregate)
- [ ] Implement cap enforcement in `ModelRouter`: track daily frontier calls, refuse if exceeded, fall back to next cheapest provider

### R4.4 Failure Handling Chain

- [ ] Implement retry-then-escalate in `TieredDispatcher`:
  - Tier 1 fails → retry once → if still invalid → escalate to Tier 2
  - Tier 2 fails → retry with stricter constraints → if still invalid → escalate to Tier 3
  - Tier 3 fails with selected provider → try next provider in pool
  - All Tier 3 providers fail → return structured error, flag for human review
- [ ] Add `RoutingFailure` error type to `core/errors.py`
- [ ] Update orchestrator to catch `RoutingFailure` and emit appropriate event

### R4.5 Phase R4 Tests

- [ ] Test `AnthropicAdapter` call structure (mock HTTP)
- [ ] Test `OpenAIAdapter` call structure (mock HTTP)
- [ ] Test `DGXSparkAdapter` with remote Ollama host
- [ ] Test provider selection: cheapest_qualified strategy
- [ ] Test provider selection: highest_quality strategy
- [ ] Test provider selection: prefer_local prioritizes DGX Spark and local Ollama
- [ ] Test provider fallback when first choice is unavailable
- [ ] Test daily frontier cap enforcement (allow, then deny, then fallback)
- [ ] Test full escalation chain: Tier 1 → Tier 2 → Tier 3 (provider pool)
- [ ] Test Tier 3 provider failover (first provider fails → try next)
- [ ] Test all Tier 3 providers fail → structured error
- [ ] Integration test: graph run with all tiers active (mock models at each tier)

---

## Phase R5: Observability and Tuning

Logging, metrics, and threshold tuning for the tiered router.

### R5.1 Routing Telemetry

- [ ] Log every routing decision to `routing_decisions` table:
  - Request tier, chosen tier, provider name, escalation reason, confidence, complexity, latency, tokens, cost
- [ ] Add `_log_routing_decision()` helper to `TieredDispatcher`
- [ ] Extend `MetricsCollector` in `core/logging.py` with router metrics:
  - `tier_distribution`: count of requests per tier
  - `escalation_rate`: fraction of requests escalated from each tier
  - `frontier_usage_rate`: fraction of requests reaching Tier 3
  - `provider_distribution`: count of Tier 3 requests per provider
  - `cost_by_provider`: total cost broken down by provider
  - `avg_latency_by_tier`: average latency per tier
  - `avg_quality_by_tier`: average quality score per tier

### R5.2 Dashboard Integration

- [ ] Add router metrics panel to `scripts/dashboard.py`:
  - Tier distribution chart
  - Escalation rate over time
  - Cost breakdown by tier and by provider
  - Quality score distribution by tier
  - Top escalation reasons
  - Provider availability history

### R5.3 Threshold Tuning

- [ ] Add `scripts/tune_router.py` — analyze routing_decisions and suggest threshold adjustments:
  - Identify over-escalation (high confidence requests sent to higher tiers)
  - Identify under-escalation (low quality results from lower tiers)
  - Identify cost optimization opportunities (expensive provider used when cheap one would suffice)
  - Output recommended threshold and weight changes
- [ ] Support `RouterConfig` hot-reload (re-read YAML without restart)

### R5.4 Phase R5 Tests

- [ ] Test routing decision logging to DB with provider field
- [ ] Test MetricsCollector router metrics including provider breakdown
- [ ] Test threshold tuning script with synthetic data
- [ ] Test config hot-reload changes thresholds

---

## Phase R6: Safety and Hardening

Reliability, safety rails, and production hardening.

### R6.1 Safety Rails

- [ ] Add safety classification to micro router output: `safety_flag: bool`, `safety_reason: str`
- [ ] If safety_flag is true: bypass reasoning tiers, return canned response or flag for review
- [ ] Add input sanitization: strip injection attempts, enforce max input length

### R6.2 Timeout Enforcement

- [ ] Per-tier timeout caps in RouterConfig:
  - Tier 1: 5s
  - Tier 2: 30s
  - Tier 3: 120s (may vary by provider)
- [ ] Per-provider timeout overrides in provider config
- [ ] Enforce in `TieredDispatcher` with `asyncio.wait_for()` or thread-level timeout
- [ ] On timeout: escalate to next tier or next provider (treat as failure)

### R6.3 Concurrency Control

- [ ] Add concurrency limits per tier in RouterConfig:
  - Tier 1 (micro deepseek): high concurrency (8+ workers)
  - Tier 2 (light deepseek): moderate (2–4 workers)
  - Tier 3 (frontier pool): per-provider limits (e.g., DGX Spark 2, API providers by rate limit)
- [ ] Implement semaphore-based concurrency in `TieredDispatcher`
- [ ] Queue requests when concurrency limit reached

### R6.4 GPU and Hardware Health Monitoring

- [ ] Add `core/gpu_monitor.py`:
  - Query Ollama `/api/tags` for loaded models (local workstation)
  - Track VRAM usage via `nvidia-smi` parsing (local GPU)
  - Ping DGX Spark health endpoint for remote hardware availability
  - Alert if local VRAM > 90% or KV cache pressure detected
  - Alert if DGX Spark unreachable
- [ ] Integrate health check into `TieredDispatcher`:
  - If local GPU unhealthy: route Tier 1/2 to degraded mode or queue
  - If DGX Spark unhealthy: remove from Tier 3 provider pool, prefer cloud providers
- [ ] Add provider availability tracking: mark providers as `available: false` on repeated failures, retry periodically

### R6.5 Phase R6 Tests

- [ ] Test safety flag detection and bypass
- [ ] Test per-tier timeout enforcement
- [ ] Test per-provider timeout overrides
- [ ] Test concurrency semaphore limits
- [ ] Test GPU health check parsing (local)
- [ ] Test DGX Spark health check (mock HTTP)
- [ ] Test provider availability tracking (mark down, mark up)
- [ ] Test degradation on GPU pressure

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

# PDR_TODOS.MD — Phased Release Plan

All items below are derived from `PRD.MD`. Each phase is ordered by dependency — complete earlier phases before starting later ones.

---

## Phase 0: Skeleton [COMPLETE]

Establish the repo structure, data layer, orchestrator, and agent framework so that all subsequent phases have a foundation to build on.

### 0.1 Repository Layout

- [X] Create top-level `pyproject.toml` with project metadata, dependencies, and `[dev]` extras
- [X] Create package directories: `agents/`, `graphs/`, `core/`, `data/`, `connectors/`, `eval/`, `publish/`, `publish/templates/`, `scripts/`
- [X] Add `__init__.py` to each package directory
- [X] Create `publish/out/` directory and add it to `.gitignore`
- [ ] Create `README.md` with basic project description and CLI usage

### 0.2 SQLite Schema and Data Layer

- [X] Write `data/schema.sql` with all core tables:
  - `source_docs` (doc_id, uri, source_type, retrieved_at, published_at, title, content_hash, text_path, meta_json)
  - `source_segments` (segment_id, doc_id, idx, text_path, meta_json)
  - `entities` (entity_id, type, names_json, props_json)
  - `claims` (claim_id, scope_type, scope_id, statement, claim_type, entities_json, citations_json, evidence_strength, confidence, status, first_seen_at, last_confirmed_at, supersedes_json, meta_json)
  - `metrics` (metric_id, name, unit, scope_type, scope_id, dimensions_json)
  - `metric_points` (point_id, metric_id, t, value, doc_id, segment_id, confidence, notes)
  - `relationships` (rel_id, type, from_id, to_id, confidence, citations_json)
  - `snapshots` (snapshot_id, scope_type, scope_id, created_at, hash, included_claim_ids_json, included_metric_ids_json, meta_json)
  - `deltas` (delta_id, scope_type, scope_id, from_snapshot_id, to_snapshot_id, created_at, delta_json, stability_score, summary)
  - `runs` (run_id, scope_type, scope_id, graph_id, started_at, ended_at, status, cost_json, meta_json)
  - `run_events` (event_id, run_id, t, node_id, agent_id, status, cost_json, payload_json)
- [X] Write `data/schema.sql` with certification domain tables:
  - `cert_objectives` (objective_id, cert_id, code, text, weight, prereqs_json, meta_json)
  - `cert_modules` (module_id, objective_id, version, content_json)
  - `cert_questions` (question_id, objective_id, version, qtype, content_json, grounding_claim_ids_json)
- [X] Write `data/schema.sql` with lab domain tables:
  - `lab_models` (model_id, name, family, params_b, context_len, quant, provider, revision, caps_json)
  - `lab_hardware` (hw_id, spec_json)
  - `lab_tasks` (task_id, category, prompt_template, golden_json, rubric_json)
  - `lab_runs` (lab_run_id, suite_id, model_id, hw_id, t, settings_json, cost_json)
  - `lab_results` (result_id, lab_run_id, task_id, scores_json, fail_modes_json, notes)
- [X] Implement `data/db.py` — connection management, schema initialization, migrations
- [X] Implement `data/dao_sources.py` — CRUD for source_docs and source_segments
- [X] Implement `data/dao_entities.py` — CRUD for entities and relationships
- [X] Implement `data/dao_claims.py` — CRUD for claims
- [X] Implement `data/dao_metrics.py` — CRUD for metrics and metric_points
- [X] Implement `data/dao_snapshots.py` — CRUD for snapshots and deltas
- [X] Implement `data/dao_runs.py` — CRUD for runs and run_events

### 0.3 Agent Framework

- [X] Implement `agents/base_agent.py` — base class requiring:
  - `AGENT_ID` (str)
  - `VERSION` (str)
  - `SYSTEM_PROMPT` (str)
  - `USER_TEMPLATE` (str)
  - `INPUT_SCHEMA` (Pydantic model)
  - `OUTPUT_SCHEMA` (Pydantic model)
  - `POLICY` dict (allowed_models, max_tokens, confidence_threshold, required_citations)
  - `parse(response) -> dict` method
  - `validate(output) -> None/raise` method
  - Runtime contract: input is `state: dict`, output is `delta_state: dict` merged into state
- [X] Implement `agents/registry.py` — agent registry that loads agent files by AGENT_ID key

### 0.4 Graph Definition and Loader

- [X] Implement `graphs/graph_types.py` — data structures for graph nodes with fields:
  - `name` (node id)
  - `agent` (agent registry key)
  - `inputs` (list of state keys required)
  - `outputs` (list of state keys produced)
  - `next` (next node id)
  - `on_fail` (next node id if gate_status=FAIL)
  - `retry` (count + backoff policy)
  - `budget` (optional token/$ cap override)
- [X] Implement YAML graph loader in `graphs/graph_types.py` — parse YAML files into graph structures

### 0.5 Orchestrator

- [X] Implement `core/state.py` — run state as a dict, serializable to JSON per node, with required keys: scope_type, scope_id, run_id, graph_id, budget, artifacts, and per-node outputs
- [X] Implement `core/orchestrator.py` — graph runner that for each node:
  1. Validates inputs exist in state
  2. Applies budget policy
  3. Executes agent
  4. Validates agent output schema
  5. Merges delta_state into state
  6. Emits run_event
- [X] Implement failure and retry logic:
  - Node-level retry with capped attempts
  - Failed validation routes to `on_fail` node if defined
  - If `on_fail` absent, abort graph
- [X] Implement `core/errors.py` — error types for orchestration failures
- [X] Implement `core/policies.py` — policy definitions and enforcement

### 0.6 Model Routing (Stub)

- [X] Implement `core/routing.py` — model routing interface with local-first default
  - Stub implementation that calls a local model
  - Interface for escalation to frontier models (to be wired in Phase 1)

### 0.7 Budget Tracking (Stub)

- [X] Implement `core/budgets.py` — budget tracking structure for tokens in/out, wall time, and dollar cost
  - Stub enforcement at per-node, per-run, and per-scope levels (full enforcement in Phase 4)

### 0.8 Phase 0 Tests

- [X] DAO read/write unit tests for each DAO module (SQLite round-trips)
- [X] Schema validation tests for graph node definitions
- [X] Orchestrator test with a minimal 2-node graph using mock agents
- [X] Agent base class tests verifying required attributes and parse/validate contract

---

## Phase 1: Spine Agents [COMPLETE]

Build the shared agents that all three loops depend on. These form the "spine" of the platform.

### 1.1 Connectors

- [X] Implement `connectors/web_fetch.py` — fetch web pages, return raw text/HTML
- [X] Implement `connectors/rss_fetch.py` — fetch and parse RSS/Atom feeds
- [X] Implement `connectors/file_loader.py` — load local files (PDF, text, markdown, JSON)

### 1.2 Ingestor Agent

- [X] Implement `agents/ingestor_agent.py`
  - Fetches raw sources via connectors
  - Produces source_docs and source_segments in the data layer
  - Assigns content_hash for deduplication
  - Outputs state keys: source doc IDs, segment IDs

### 1.3 Normalizer Agent

- [X] Implement `agents/normalizer_agent.py`
  - Normalizes raw text into consistent structure
  - Handles different source formats (HTML, PDF text, RSS content)
  - Outputs cleaned, structured text segments

### 1.4 Entity Resolver Agent

- [X] Implement `agents/entity_resolver_agent.py`
  - Extracts entities from normalized segments
  - Resolves duplicate entities (name variants, aliases)
  - Creates entity records and relationships in data layer
  - Outputs entity IDs and relationship mappings

### 1.5 Claim Extractor Agent

- [X] Implement `agents/claim_extractor_agent.py`
  - Extracts atomic claims from text segments
  - Each claim linked to citations (doc_id + segment_id)
  - Assigns evidence_strength and confidence scores
  - Sets claim status (active, disputed, superseded)
  - Outputs claim IDs with citation references

### 1.6 Metric Extractor Agent

- [X] Implement `agents/metric_extractor_agent.py`
  - Extracts quantitative metrics from text segments
  - Each metric point includes unit + dimensions
  - Links to source doc/segment for provenance
  - Outputs metric IDs and metric_point records

### 1.7 Contradiction Agent

- [X] Implement `agents/contradiction_agent.py`
  - Compares new claims against existing claims for the same scope
  - Detects contradictions and sets claim status to `disputed`
  - Produces contradiction report with both sides and citations

### 1.8 QA Validator Agent

- [X] Implement `agents/qa_validator_agent.py`
  - Enforces global gate rules:
    - No claim without citations
    - Every citation resolves to a doc+segment
    - Metric points include unit + dimensions
    - No publish without snapshot + delta
  - Returns `gate_status` (PASS/FAIL) and list of violations

### 1.9 Delta Agent (Snapshot + Delta Engine)

- [X] Implement `agents/delta_agent.py`
  - Creates snapshots: captures current claim IDs + metric IDs for a scope, computes hash
  - Computes deltas: structured diff on claim IDs + statement similarity vs previous snapshot
  - Produces delta_json with added/removed/changed claims and metrics
  - Computes stability_score and summary

### 1.10 Model Routing (Full)

- [X] Wire `core/routing.py` to actual local and frontier model adapters
  - Escalate when: extraction confidence < threshold, missing citations detected repeatedly, contradiction ambiguity high, synthesis requires high fidelity
  - Log all escalation decisions to run_events

### 1.11 Phase 1 Tests

- [X] Unit tests for each spine agent's parse/validate methods with sample inputs
- [X] Connector tests with mock HTTP responses
- [X] Integration test: run ingestor → normalizer → entity_resolver → claim_extractor chain with fixture data
- [X] QA validator tests covering each gate rule (pass and fail cases)
- [X] Delta computation determinism tests (same input produces same delta)

---

## Phase 2: Product Loop Agents and Graphs [COMPLETE]

Build the domain-specific agents and wire up the three complete graph loops.

### 2.1 Certification Loop

- [X] Implement `agents/synthesizer_agent.py` — general synthesis agent constrained to provided claims, metrics, and delta reports only
- [X] Implement `agents/lesson_composer_agent.py`
  - Composes lesson modules (L1/L2/L3) per objective
  - Content grounded in extracted claims
  - Outputs content_json for cert_modules table
- [X] Implement `agents/question_generator_agent.py`
  - Generates question bank per objective
  - Each question links to grounding claim IDs
  - Question count proportional to objective weight
  - Supports multiple question types (qtype)
  - Outputs content_json for cert_questions table
- [X] Write `graphs/certification_graph.yaml` — full node chain:
  1. blueprint_ingest (ingestor)
  2. objective_graph (entity_resolver)
  3. grounding_sweep (normalizer)
  4. claim_extraction (claim_extractor)
  5. lesson_composition (lesson_composer)
  6. question_generation (question_generator)
  7. qa_validation (qa_validator) — on_fail routes back to claim_extraction
  8. snapshot (delta_agent)
  9. publish (publisher)
- [X] Certification-specific QA gate: every objective has a module + minimum question count proportional to weight
- [X] Implement `scripts/run_cert.py` — CLI entrypoint: `python -m scripts.run_cert --cert_id <id>`

### 2.2 Dossier Loop

- [X] Write `graphs/dossier_graph.yaml` — full node chain:
  1. topic_ingest (ingestor)
  2. normalize (normalizer)
  3. entity_resolution (entity_resolver)
  4. claim_extraction (claim_extractor)
  5. metric_extraction (metric_extractor)
  6. contradiction_check (contradiction_agent)
  7. snapshot (delta_agent)
  8. synthesis (synthesizer) — constrained to provided claims, metrics, delta report
  9. publish (publisher)
- [X] Dossier-specific QA gate: contradictions surfaced with claim status `disputed` and dispute notes from structured fields only
- [X] Dossier outputs: living dossier page, timeline of key changes, metric tables, "what changed" delta memo, contradiction list and claim status changes
- [X] Implement `scripts/run_dossier.py` — CLI entrypoint: `python -m scripts.run_dossier --topic_id <id>`

### 2.3 Lab Loop

- [X] Implement `eval/rubrics.py` — scoring rubrics with required score components
- [X] Implement `eval/lab_tasks.py` — task definitions with prompt templates, golden answers, rubric references
- [X] Implement `eval/scoring.py` — scoring engine that produces scores_json and fail_modes_json
- [X] Write `graphs/lab_graph.yaml` — full node chain:
  1. suite_assembly (ingestor)
  2. benchmark_run (synthesizer)
  3. scoring (metric_extractor)
  4. trend_metrics (synthesizer)
  5. routing_recommendation (synthesizer)
  6. snapshot (delta_agent)
  7. publish (publisher)
- [X] Lab-specific QA gate: every result ties to model spec + hardware spec; rubric scoring produces required score components
- [X] Lab outputs: benchmark run logs + scored results, trend report, recommended configs, routing policy suggestions, "tricks playbook" (prompt patterns + known failure modes)
- [X] Implement `scripts/run_lab.py` — CLI entrypoint: `python -m scripts.run_lab --suite_id <id>`

### 2.4 Phase 2 Tests

- [X] Integration test: certification graph end-to-end with fixture dataset (1 certification, 2 objectives)
- [X] Integration test: dossier graph end-to-end with fixture dataset (1 dossier, 3 sources)
- [X] Integration test: lab graph end-to-end with fixture dataset (1 suite, 2 tasks)
- [X] Lesson composer output schema validation tests
- [X] Question generator grounding tests (all questions reference valid claim IDs)
- [X] Lab scoring determinism tests

---

## Phase 3: Publisher [COMPLETE]

Build the publishing pipeline that packages and renders outputs for all three loops.

### 3.1 Publisher Agent

- [X] Implement `agents/publisher_agent.py`
  - Render only — publisher cannot synthesize
  - Writes to `publish/out/<scope>/<version>/`
  - Must produce for every publish:
    - `manifest.json` (version, snapshot_id, delta_id, generated_at)
    - `artifacts.json` (paths + hashes)
    - Domain-specific artifacts (modules, questions, dossier pages, lab tables)
  - Only publishes if QA gate passed

### 3.2 Versioning Scheme

- [X] Certification: semver (e.g., `1.0.0`, `1.1.0`)
- [X] Dossier: date-based versions (e.g., `2026-02-16` snapshot label)
- [X] Lab: suite-based (suite version + model revision)

### 3.3 Renderer and Templates

- [X] Implement `publish/renderer.py` — renders JSON artifacts into output formats
- [X] Create templates in `publish/renderer.py` for:
  - Certification: objective map, lesson modules, question bank, changelog/delta memo
  - Dossier: living dossier page, timeline, metric tables, delta memo, contradiction list
  - Lab: benchmark logs, trend report, config recommendations, tricks playbook
- [X] JSON artifacts always produced; static Markdown rendered automatically

### 3.4 Export Formats

- [X] Certification exports: JSON, CSV, and Markdown
- [X] Dossier exports: JSON and Markdown
- [X] Lab exports: JSON and Markdown

### 3.5 Phase 3 Tests

- [X] Golden tests: "expected artifacts" hash comparisons for publish output with known inputs
- [X] Manifest.json schema validation tests
- [X] Artifacts.json integrity tests (all listed paths exist, hashes match)
- [X] Test that publish is blocked when QA gate has not passed

---

## Phase 4: Hardening [COMPLETE]

Improvements for robustness, observability, and automation.

### 4.1 Budget Enforcement (Full)

- [X] Full budget enforcement at per-node, per-run, and per-scope levels
- [X] Degradation behavior when budget exceeded: fewer sources, fewer questions, skip deep synthesis
- [X] Human review flag when budget exceeded and degradation is not acceptable
- [X] Cost tracking: tokens in/out (estimated if provider doesn't return exact), wall time, dollar cost for frontier models

### 4.2 Retry and Resilience

- [X] Node-level retry with configurable count and backoff policy
- [X] Graceful handling of model API failures (timeouts, rate limits) — `ModelAPIError` retried by orchestrator
- [X] State checkpointing so failed runs can resume from last successful node

### 4.3 Contradiction Logic Improvements

- [X] Advanced contradiction resolution workflows — domain-specific QA gates
- [X] Human-in-the-loop queue for ambiguous contradictions — human review flag on budget ledger
- [X] Claim lifecycle management: active → disputed → superseded → archived

### 4.4 Scoring Rubric Improvements

- [X] Expanded rubric library for lab benchmarks (6 built-in: accuracy, reasoning, coding, summarization, instruction_following, safety)
- [X] Configurable scoring dimensions per task category via `CATEGORY_RUBRICS` mapping
- [X] Baseline comparison with statistical significance checks (Welch's t-test approximation)

### 4.5 Observability

- [X] Structured logging per node execution: run_id, scope_id, node_id, agent_id, model_used, cost
- [X] Log redaction for API keys and sensitive text
- [X] Observable metrics via `MetricsCollector`:
  - Run duration
  - Token usage
  - Frontier usage rate
  - QA fail rate per agent
  - Delta magnitude distribution

### 4.6 Scheduler and Notifications (v1)

- [ ] Cron scheduler to run weekly/monthly loops automatically
- [ ] Notification hooks (email/webhook) on run completion or failure
- [ ] Simple web-based metrics dashboards

### 4.7 Additional v1 Features

- [ ] Learner telemetry ingestion (for certification loop, when learners exist)
- [ ] License flags on SourceDoc to prevent re-publishing restricted content verbatim

---

## Open Decisions (Defaults for v0)

These decisions are recorded here per PRD section 22. Revisit as needed.

| Decision | Default (v0) |
|---|---|
| Graph runtime | Custom YAML runner (consider LangGraph later) |
| Model interface | Unified adapter for local + frontier |
| Citation granularity | segment_id + span offsets |
| Delta method | Structured diff on claim IDs + statement similarity |

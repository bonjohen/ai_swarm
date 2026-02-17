# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Unified AI Swarm Platform that supports three product loops (Certification Engine, Living Dossiers, AI Lab Observatory) using shared agents, shared data structures, shared orchestration, and shared publishing. See `PRD.MD` for full requirements.

Tech stack: Python, SQLite + filesystem storage, YAML graph definitions. Local-first execution, batch/scheduled runs.

## Build and Run Commands

```bash
# Install dependencies (once pyproject.toml exists)
pip install -e ".[dev]"

# Run the three product loops via CLI
python -m scripts.run_cert --cert_id <id>
python -m scripts.run_dossier --topic_id <id>
python -m scripts.run_lab --suite_id <id>

# Tests
pytest
pytest tests/unit/
pytest tests/integration/
pytest tests/<file>::<test_name>   # single test
```

## Architecture

### Six Core Components

1. **Graph Runner (Orchestrator)** (`core/orchestrator.py`): executes YAML graph definitions, manages run state as a dict persisted between nodes, enforces budgets. Supports state checkpointing and resume from last successful node.
2. **Agent Runtime** (`agents/`): loads agent files, builds prompts, routes to local or frontier model, parses/validates JSON outputs. Each agent produces a `delta_state: dict` merged into the run state.
3. **Data Layer** (`data/`): SQLite for structured objects (sources, entities, claims, metrics, snapshots, deltas, runs) + filesystem for raw docs/chunks/artifacts. DAOs per domain object.
4. **QA Gate** (`agents/qa_validator_agent.py`): validates structural integrity — global rules (claim citations, doc/segment resolution, metric units, publish prerequisites) plus domain-specific rules: cert (objective has module + min questions proportional to weight), dossier (disputed claims have correct status, contradictions have structured reason), lab (hw spec present, models have scores, metrics present if referenced).
5. **Snapshot + Delta Engine** (`agents/delta_agent.py`): versions outputs per scope and computes semantic diffs (structured diff on claim IDs + statement similarity).
6. **Publisher** (`agents/publisher_agent.py` + `publish/renderer.py`): renders and packages artifacts to `publish/out/<scope>/<version>/`. Produces `manifest.json`, `artifacts.json`, domain JSON artifacts, Markdown reports, and CSV exports (cert only). Versioning: cert=semver, dossier=date-based, lab=suite-based. Publisher cannot synthesize — render only. All file writes use binary mode for cross-platform hash consistency.

### Three Graph Loops (YAML in `graphs/`)

- **Certification**: blueprint_ingest → objective_graph → grounding_sweep → claim_extraction → lesson_composition → question_generation → qa_validation → snapshot → publish
- **Dossier**: topic_ingest → normalize → entity_resolution → claim_extraction → metric_extraction → contradiction_check → snapshot → synthesis → publish
- **Lab**: suite_assembly → benchmark_run → scoring → trend_metrics → routing_recommendation → snapshot → publish

Each graph node specifies: `agent` (registry key), `inputs`/`outputs` (state keys), `next`, `on_fail`, `retry` policy, optional `budget` cap.

### Agent Contract

Every agent file must define: `AGENT_ID`, `VERSION`, `SYSTEM_PROMPT`, `USER_TEMPLATE`, `INPUT_SCHEMA` (Pydantic), `OUTPUT_SCHEMA`, `POLICY` (routing + budgets + constraints), `parse(response) -> dict`, `validate(output) -> None/raise`. Agents output JSON only — no freeform prose unless the output schema explicitly requires it.

### Model Routing

Default: local model. Escalate to frontier when: extraction confidence below threshold, missing citations detected repeatedly, contradiction ambiguity high, or synthesis requires high fidelity. All escalation decisions are logged.

### Budget System

Tracked per token in/out, wall time, and dollar cost. Enforced at per-node, per-run, and per-scope levels. Degradation activates at 80% of budget (configurable): reduces max_sources, max_questions, skips deep synthesis. On hard exceed: `budget_degraded` event emitted and human review flagged. Per-node cost breakdown tracked.

### Observability (`core/logging.py`)

Structured JSON logging with redaction of API keys/tokens. `MetricsCollector` tracks run duration, token usage, frontier usage rate, QA fail rate per agent, delta magnitude. `log_node_event()` emits structured records for each node execution.

### Run Execution Flow

Each run is scoped to `(certification_id | topic_id | lab_suite_id)` and produces: run record, snapshot (if QA passes), delta vs previous snapshot, published artifacts. Node execution: validate inputs → apply budget → execute agent → validate output schema → merge delta_state → emit run_event. Failed validation routes to `on_fail` node or aborts.

## Key Design Rules

- Every published statement must trace back to citations (auditable provenance).
- Synthesis agents may only reference claims, metrics, and delta reports provided to them.
- Published artifacts go only in `publish/out/` (gitignored).
- API keys stored in env vars, never in repo.
- v0 targets static site + JSON artifacts; no heavy UI.

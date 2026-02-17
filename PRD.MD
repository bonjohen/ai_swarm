# PDR: Unified AI Swarm Platform for Certification Engine, Living Dossiers, and AI Lab Observatory

## 0. Document Purpose

Specify a single implementable platform that supports three recurring “product loops” using shared agents, shared data structures, shared orchestration, and shared publishing. This PDR is written to hand to a coding agent (or to implement yourself) with minimal ambiguity.

---

## 1. Goals

### 1.1 Primary Goals

1. **Reusable agents**: each agent defined once (prompt + behavior + parsing + policies) and usable in multiple graphs.
2. **Three loop graphs**:

   * Certification / Training loop
   * Living Technical Dossier loop
   * AI Lab Performance & Tricks loop
3. **Single shared spine**:

   * Source registry
   * Entity store
   * Claim store
   * Metric time series
   * Snapshots + deltas
   * QA gating
4. **Deterministic, versioned outputs**:

   * Every publish corresponds to a snapshot.
   * Every snapshot has a delta relative to the previous snapshot.

### 1.2 Secondary Goals

* Local-first inference with controlled escalation to frontier models.
* Explicit budget accounting per run / agent / scope.
* Auditable provenance: every published statement can trace back to citations.

---

## 2. Non-Goals

* Full LMS implementation (payments, user accounts, etc.) in v0.
* Heavy UI in v0 (target static site + JSON artifacts).
* Perfect truth verification (we manage uncertainty via citations, contradictions, and confidence).
* Continuous background “always on” crawling (v0 is scheduled/batch).

---

## 3. Product Scope

### 3.1 Loop Outputs

#### Certification Loop Outputs

* Objective map (graph)
* Lesson modules (L1/L2/L3)
* Question bank (grounded)
* Changelog / delta memo
* Versioned exports (JSON/CSV/MD)

#### Dossier Loop Outputs

* Living dossier page
* Timeline of key changes
* Metric dashboards (simple tables in v0)
* “What changed since last run” delta memo
* Contradiction list and claim status changes

#### AI Lab Loop Outputs

* Benchmark run logs + scored results
* Trend report vs baseline
* Recommended configs (quant, ctx, temperature)
* Routing policy suggestions (local vs frontier thresholds)
* “Tricks playbook” (prompt patterns + known failure modes)

---

## 4. Users and Use Cases

### 4.1 Primary User

You (operator) running a private AI factory to create compounding assets (courses, dossiers, lab reports).

### 4.2 Use Cases

1. Add certification → generate course + question bank → publish.
2. Add topic dossier → weekly scan + monthly synthesis → publish with deltas.
3. Add model config → weekly benchmark suite → publish trend + routing recommendations.

---

## 5. Functional Requirements

### 5.1 v0 Requirements (Minimum Build)

**Orchestration**

* Run each loop on-demand via CLI.
* Deterministic graph execution with node retry policies.
* State persistence between nodes.

**Agents**

* Agent definitions as files, reusable across graphs.
* Each agent:

  * prompt(s)
  * input schema
  * output schema
  * parse/validate
  * routing policy hook

**Core Data**

* Store:

  * SourceDoc, Citation
  * Entity
  * Claim (atomic)
  * MetricSeries (time series)
  * Snapshot and DeltaReport
  * Run logs + costs

**Publishing**

* Export artifacts to `publish/` directory:

  * static markdown/html optional
  * JSON artifacts always
* Only publish if QA passes.

**Routing**

* Local-first model selection.
* Escalate to frontier based on:

  * low confidence
  * ambiguous contradiction
  * synthesis complexity
* Log all escalation decisions.

### 5.2 v1 Requirements (Next Build)

* Scheduler (cron) to run weekly/monthly loops automatically.
* Notification hooks (email/webhook).
* Metrics dashboards (simple web view).
* Learner telemetry ingestion (if/when you have learners).
* Advanced contradiction resolution workflows (human-in-the-loop queue).

---

## 6. System Architecture

### 6.1 High-Level Components

1. **Graph Runner (Orchestrator)**: executes graph definitions; manages state; enforces budgets.
2. **Agent Runtime**: loads agent files; builds prompts; routes model; parses outputs.
3. **Data Layer (SQLite + file store)**:

   * SQLite for structured objects & indices.
   * File store for raw docs, chunks, and artifacts.
4. **QA Gate**: validates structural integrity and grounding constraints.
5. **Snapshot + Delta Engine**: versions outputs and computes semantic changes.
6. **Publisher**: renders and packages outputs.

### 6.2 Execution Model

Batch runs:

* Run scope = (certification_id | topic_id | lab_suite_id)
* Each run produces:

  * Run record
  * Snapshot (if QA passes)
  * Delta vs previous snapshot
  * Published artifacts

---

## 7. Repository Layout

```
ai_swarm/
  README.md
  pyproject.toml

  agents/
    __init__.py
    base_agent.py
    registry.py
    ingestor_agent.py
    normalizer_agent.py
    entity_resolver_agent.py
    claim_extractor_agent.py
    metric_extractor_agent.py
    contradiction_agent.py
    qa_validator_agent.py
    delta_agent.py
    synthesizer_agent.py
    lesson_composer_agent.py
    question_generator_agent.py
    publisher_agent.py

  graphs/
    __init__.py
    graph_types.py
    certification_graph.yaml
    dossier_graph.yaml
    lab_graph.yaml

  core/
    orchestrator.py
    state.py
    budgets.py
    routing.py
    policies.py
    errors.py

  data/
    db.py
    schema.sql
    dao_sources.py
    dao_entities.py
    dao_claims.py
    dao_metrics.py
    dao_snapshots.py
    dao_runs.py

  connectors/
    web_fetch.py
    rss_fetch.py
    file_loader.py

  eval/
    rubrics.py
    lab_tasks.py
    scoring.py

  publish/
    renderer.py
    templates/
    out/                # generated artifacts (gitignored)

  scripts/
    run_cert.py
    run_dossier.py
    run_lab.py
```

---

## 8. Graph Definition Format

Use YAML for graphs (declarative), referencing agent names.

### 8.1 Node Schema

* `name`: node id
* `agent`: agent registry key
* `inputs`: state keys required
* `outputs`: state keys produced
* `next`: next node id
* `on_fail`: next node id if `gate_status=FAIL`
* `retry`: count + backoff policy
* `budget`: optional token/$ cap override

### 8.2 Example (fragment)

```yaml
entry: blueprint_ingest
nodes:
  blueprint_ingest:
    agent: ingestor
    next: objective_graph

  qa_validation:
    agent: qa_validator
    on_fail: claim_extraction
    next: snapshot

  publish:
    agent: publisher
    end: true
```

---

## 9. Agent File Spec

Each agent file must provide:

### 9.1 Required Attributes

* `AGENT_ID`
* `VERSION`
* `SYSTEM_PROMPT`
* `USER_TEMPLATE`
* `INPUT_SCHEMA` (pydantic model or JSON schema)
* `OUTPUT_SCHEMA`
* `POLICY` (routing + budgets + constraints)
* `parse(response) -> dict`
* `validate(output) -> None/raise`

### 9.2 Runtime Contract

Input: `state: dict`
Output: `delta_state: dict` merged into state.

### 9.3 Common Policies

* allowed models (local list; frontier list)
* max tokens
* confidence threshold
* required citations / grounding

---

## 10. Shared Data Structures

### 10.1 Canonical Objects (spine)

* `SourceDoc`
* `Citation`
* `Entity`
* `Claim`
* `MetricSeries`
* `Relationship`
* `Snapshot`
* `DeltaReport`
* `Run`

(You already requested these earlier; implement them as DB tables + JSON fields.)

---

## 11. SQLite Schema (v0)

### 11.1 Core Tables (minimal)

* `source_docs(doc_id TEXT PK, uri TEXT, source_type TEXT, retrieved_at TEXT, published_at TEXT, title TEXT, content_hash TEXT, text_path TEXT, meta_json TEXT)`
* `source_segments(segment_id TEXT PK, doc_id TEXT, idx INT, text_path TEXT, meta_json TEXT)`
* `entities(entity_id TEXT PK, type TEXT, names_json TEXT, props_json TEXT)`
* `claims(claim_id TEXT PK, scope_type TEXT, scope_id TEXT, statement TEXT, claim_type TEXT, entities_json TEXT, citations_json TEXT, evidence_strength REAL, confidence REAL, status TEXT, first_seen_at TEXT, last_confirmed_at TEXT, supersedes_json TEXT, meta_json TEXT)`
* `metrics(metric_id TEXT PK, name TEXT, unit TEXT, scope_type TEXT, scope_id TEXT, dimensions_json TEXT)`
* `metric_points(point_id TEXT PK, metric_id TEXT, t TEXT, value REAL, doc_id TEXT, segment_id TEXT, confidence REAL, notes TEXT)`
* `relationships(rel_id TEXT PK, type TEXT, from_id TEXT, to_id TEXT, confidence REAL, citations_json TEXT)`
* `snapshots(snapshot_id TEXT PK, scope_type TEXT, scope_id TEXT, created_at TEXT, hash TEXT, included_claim_ids_json TEXT, included_metric_ids_json TEXT, meta_json TEXT)`
* `deltas(delta_id TEXT PK, scope_type TEXT, scope_id TEXT, from_snapshot_id TEXT, to_snapshot_id TEXT, created_at TEXT, delta_json TEXT, stability_score REAL, summary TEXT)`
* `runs(run_id TEXT PK, scope_type TEXT, scope_id TEXT, graph_id TEXT, started_at TEXT, ended_at TEXT, status TEXT, cost_json TEXT, meta_json TEXT)`
* `run_events(event_id TEXT PK, run_id TEXT, t TEXT, node_id TEXT, agent_id TEXT, status TEXT, cost_json TEXT, payload_json TEXT)`

### 11.2 Domain Tables (v0 minimal)

Certification:

* `cert_objectives(objective_id TEXT PK, cert_id TEXT, code TEXT, text TEXT, weight REAL, prereqs_json TEXT, meta_json TEXT)`
* `cert_modules(module_id TEXT PK, objective_id TEXT, version TEXT, content_json TEXT)`
* `cert_questions(question_id TEXT PK, objective_id TEXT, version TEXT, qtype TEXT, content_json TEXT, grounding_claim_ids_json TEXT)`

Lab:

* `lab_models(model_id TEXT PK, name TEXT, family TEXT, params_b REAL, context_len INT, quant TEXT, provider TEXT, revision TEXT, caps_json TEXT)`
* `lab_hardware(hw_id TEXT PK, spec_json TEXT)`
* `lab_tasks(task_id TEXT PK, category TEXT, prompt_template TEXT, golden_json TEXT, rubric_json TEXT)`
* `lab_runs(lab_run_id TEXT PK, suite_id TEXT, model_id TEXT, hw_id TEXT, t TEXT, settings_json TEXT, cost_json TEXT)`
* `lab_results(result_id TEXT PK, lab_run_id TEXT, task_id TEXT, scores_json TEXT, fail_modes_json TEXT, notes TEXT)`

---

## 12. Orchestrator Design

### 12.1 State Model

* `state` is a dict persisted between nodes (serialize to JSON per node).
* Required keys:

  * `scope_type`, `scope_id`
  * `run_id`
  * `graph_id`
  * `budget`
  * `artifacts` (paths)
  * per-node outputs (claims, modules, deltas, etc.)

### 12.2 Node Execution

For each node:

1. Validate inputs exist in state
2. Apply budget policy
3. Execute agent
4. Validate agent output schema
5. Merge delta_state → state
6. Emit run_event

### 12.3 Failure & Retry

* Node-level retry with capped attempts.
* If agent fails validation → mark node failed and route to `on_fail` if defined.
* If `on_fail` absent → abort graph.

---

## 13. Model Routing and Budgeting

### 13.1 Routing Policy

Default: local.

Escalate when:

* extraction confidence < threshold
* missing citations detected repeatedly
* contradiction ambiguity high
* synthesis requires high fidelity

### 13.2 Budget System

Budgets tracked as:

* tokens in/out (estimated if provider doesn’t return exact)
* wall time
* $ cost for frontier models

Budgets enforced at:

* per-node cap
* per-run cap
* per-scope cap (e.g., per objective)

If a budget would be exceeded:

* degrade: fewer sources / fewer questions / skip deep synthesis
* or escalate to human review (flag)

---

## 14. Quality Gates

### 14.1 Global Gate Rules (v0)

* No claim without citations.
* Every citation must resolve to a doc+segment.
* Metric points must include unit + dimensions.
* No publish without snapshot + delta.
* Question must link to claim IDs.

### 14.2 Dossier-Specific Gate

* Contradictions must be surfaced:

  * claim status set to `disputed`
  * dossier synthesis includes dispute note (from structured fields only)

### 14.3 Certification-Specific Gate

* Every objective has module + minimum question count proportional to weight.

### 14.4 Lab-Specific Gate

* Every result ties to model spec + hardware spec.
* Rubric scoring must produce required score components.

---

## 15. The Three Graphs (v0)

### 15.1 Certification Graph Nodes

1. blueprint_ingest (ingestor)
2. objective_graph (graph builder / entity resolver)
3. grounding_sweep (ingestor + normalizer)
4. claim_extraction (claim_extractor)
5. lesson_composition (lesson_composer)
6. question_generation (question_generator)
7. qa_validation (qa_validator)
8. snapshot (snapshot+delta)
9. publish (publisher)

### 15.2 Dossier Graph Nodes

1. topic_ingest
2. normalize
3. entity_resolution
4. claim_extraction
5. metric_extraction
6. contradiction_check
7. snapshot
8. synthesis
9. publish

### 15.3 Lab Graph Nodes

1. suite_assembly
2. benchmark_run (runner)
3. scoring
4. trend_metrics (metric_extractor / aggregator)
5. routing_recommendation (synthesizer constrained to results)
6. snapshot
7. publish

---

## 16. Publishing (v0)

### 16.1 Output Contract

Publisher writes only to `publish/out/<scope>/<version>/...`

Must produce:

* `manifest.json` (version, snapshot_id, delta_id, generated_at)
* `artifacts.json` (paths + hashes)
* Domain artifacts (modules/questions/dossier/lab tables)

### 16.2 Versions

* Certification: semver.
* Dossiers: date-based versions (e.g., `YYYY-MM` snapshot label).
* Lab: suite-based (suite version + model revision).

---

## 17. Observability

### 17.1 Logging

* Structured logs per node execution:

  * run_id, scope_id, node_id, agent_id, model_used, cost

### 17.2 Metrics

* Run duration
* Token usage
* Frontier usage rate
* QA fail rate per agent
* Delta magnitude distribution
* Topic volatility score trend

---

## 18. Testing Strategy

### 18.1 Unit Tests

* Schema validation for agent outputs.
* DAO read/write tests (SQLite).
* Delta computation determinism.
* QA gate logic.

### 18.2 Integration Tests

* Run each graph with a tiny fixture dataset:

  * 1 certification with 2 objectives
  * 1 dossier with 3 sources
  * 1 lab suite with 2 tasks

### 18.3 Golden Tests

* “Expected artifacts” hash comparisons for publish output.

---

## 19. Security and Safety (Practical)

* Store API keys outside repo (env vars).
* Log redaction for keys and sensitive text.
* License flags on SourceDoc to avoid re-publishing restricted content verbatim.
* Keep citations as references; avoid copying large text chunks into outputs.

---

## 20. Deployment (v0)

* Local execution on your workstation/server.
* SQLite + filesystem storage.
* CLI entrypoints:

  * `python -m scripts.run_cert --cert_id ...`
  * `python -m scripts.run_dossier --topic_id ...`
  * `python -m scripts.run_lab --suite_id ...`

(v1 adds cron scheduler and notifications.)

---

## 21. Implementation Plan

### Phase 0: Skeleton (1–2 days)

* repo layout
* SQLite schema + DAOs
* orchestrator + graph loader
* agent base class + registry

### Phase 1: Spine Agents (2–5 days)

* ingestor, normalizer, entity resolver
* claim extractor, metric extractor
* QA validator, snapshot+delta

### Phase 2: Product Loops (5–10 days)

* certification-specific agents (lesson, questions)
* dossier synthesis agent
* lab runner + scoring + synthesis

### Phase 3: Publisher (2–4 days)

* JSON outputs + manifest
* optional static rendering

### Phase 4: Hardening (ongoing)

* budgets
* retries
* improved contradiction logic
* better scoring rubrics
* scheduler + notifications

---

## 22. Open Decisions (choose defaults now)

1. **Graph runtime**: custom YAML runner (recommended v0), or LangGraph (later).
2. **Model interface**: unify local + frontier under one adapter (recommended).
3. **Citation granularity**: segment_id + span offsets (recommended).
4. **Delta method**: structured diff on claim ids + statement similarity (recommended simple start).

---

## 23. Appendix: Minimal Agent Output Rules (v0 defaults)

* Agents output JSON only.
* No freeform prose unless the output object explicitly requires it (e.g., `LessonModule.content_json`).
* Synthesis agents may only reference:

  * claims provided
  * metrics provided
  * delta report provided
* Publisher cannot synthesize—render only.

---

If you want the next concrete step, I can generate the **actual graph YAML files** and **agent file templates** (with JSON schemas and strict parsing rules) for v0, matching this PDR.

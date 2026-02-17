# AI Swarm Platform — Graph Architecture

## Overview

The platform runs three product loops (Certification, Dossier, Lab Observatory), each defined as a YAML directed graph. The **Graph Runner** (`core/orchestrator.py`) walks the graph node-by-node, calling the agent specified at each node, merging its output into a shared **run state** dict, and advancing to the next node.

All three graphs share the same agent pool, the same orchestrator, and the same publish pipeline. They differ in which agents they invoke and in what order.

```
                         +---------------------+
                         |  schedule_config.yaml|
                         |  (cron triggers)     |
                         +----------+----------+
                                    |
                         +----------v----------+
                         |     Scheduler        |
                         | core/scheduler.py    |
                         +----------+----------+
                                    |
               +--------------------+--------------------+
               |                    |                    |
    +----------v---+     +----------v---+     +----------v---+
    | run_cert.py  |     |run_dossier.py|     | run_lab.py   |
    +----------+---+     +----------+---+     +----------+---+
               |                    |                    |
    +----------v---+     +----------v---+     +----------v---+
    | cert graph   |     |dossier graph |     | lab graph    |
    | (9 nodes)    |     | (9 nodes)    |     | (7 nodes)    |
    +----------+---+     +----------+---+     +----------+---+
               |                    |                    |
               +--------------------+--------------------+
                                    |
                         +----------v----------+
                         |  Graph Runner        |
                         |  (orchestrator)      |
                         |  - budget enforcement|
                         |  - retry logic       |
                         |  - checkpointing     |
                         +----------+----------+
                                    |
                         +----------v----------+
                         |  Agent Runtime       |
                         |  BaseAgent.run()     |
                         |  - build_prompt()    |
                         |  - extract_json()    |
                         |  - parse/validate    |
                         |  - repair retry loop |
                         +----------+----------+
                                    |
                    +---------------+---------------+
                    |                               |
         +----------v----------+         +----------v----------+
         |  Local Model        |         |  Frontier Model     |
         |  (Ollama adapter)   |         |  (API adapter)      |
         |  format: json       |         |  escalation only    |
         +---------------------+         +---------------------+
```

---

## Shared Infrastructure

### Agent Runtime (`agents/base_agent.py`)

Every agent call follows the same lifecycle:

```
build_prompt(state)  -->  model_call(system, user)  -->  extract_json(raw)
                                                              |
                                                   +----------v----------+
                                                   |  parse(clean_json)  |
                                                   +----------+----------+
                                                              |
                                                   +----------v----------+
                                                   |  validate(output)   |
                                                   +----------+----------+
                                                              |
                                                     pass?  /   \ fail?
                                                           /     \
                                                  return delta   repair prompt
                                                                (up to 2x)
```

- **extract_json()** — strips markdown fences, preamble/postamble from LLM responses
- **Repair loop** — on parse/validate failure, sends the error back to the model and retries (max 2 repair attempts)
- **3 deterministic agents** override `run()` and skip the LLM: `delta`, `qa_validator`, `publisher`

### Graph Runner (`core/orchestrator.py`)

```
for each node in graph:
    1. Check required inputs exist in state
    2. Check budget (per-node cap)
    3. Inject degradation hints if budget >= 80%
    4. Execute agent.run(state, model_call)
    5. Merge delta_state into state
    6. On success: advance to node.next (or finish if node.end)
    7. On failure: retry (with backoff) or route to node.on_fail
```

### Publish Pipeline (`agents/publisher_agent.py`)

All three graphs end with the same publisher. Versioning varies by scope:

| Scope | Versioning | Example |
|-------|-----------|---------|
| cert  | semver    | `1.0.0`, `1.1.0` |
| topic (dossier) | date-based | `2026-02-17` |
| lab   | suite-based | `bench-1-dabe0de1` |

Output: `publish/out/<scope_type>/<scope_id>/<version>/`

Every publish produces: `manifest.json`, `artifacts.json`, domain-specific JSON files, `report.md`, and CSVs (cert only).

---

## Graph 1: Certification Engine

**Purpose:** Ingest study materials, extract claims, compose lessons, generate exam questions, validate, snapshot, and publish a certification package.

**Graph file:** `graphs/certification_graph.yaml`

```
+------------------+     +------------------+     +------------------+
|  blueprint_      |     |  objective_      |     |  grounding_      |
|  ingest          +---->|  graph           +---->|  sweep           |
|                  |     |                  |     |                  |
|  Agent: ingestor |     | Agent: entity_   |     | Agent: normalizer|
|                  |     |   resolver       |     |                  |
|  IN:  sources    |     | IN:  source_     |     | IN:  source_     |
|                  |     |   segments       |     |   segments       |
|  OUT: doc_ids    |     | OUT: entities    |     | OUT: normalized_ |
|    segment_ids   |     |   relationships  |     |   segments       |
|    source_docs   |     |   objectives     |     |                  |
|    source_segs   |     |                  |     |                  |
+------------------+     +------------------+     +--------+---------+
                                                           |
              +--------------------------------------------+
              |
+-------------v----+     +------------------+     +------------------+
|  claim_          |     |  lesson_         |     |  question_       |
|  extraction      +---->|  composition     +---->|  generation      |
|                  |     |                  |     |                  |
| Agent: claim_    |     | Agent: lesson_   |     | Agent: question_ |
|   extractor      |     |   composer       |     |   generator      |
|                  |     |                  |     |                  |
| IN:  normalized_ |     | IN:  objectives  |     | IN:  objectives  |
|   segments,      |     |   claims         |     |   claims         |
|   entities       |     |   entities       |     |   modules        |
|                  |     |                  |     |                  |
| OUT: claims      |     | OUT: modules     |     | OUT: questions   |
|  (with citations)|     |  (L1/L2/L3 per   |     |  (grounded to    |
|                  |     |   objective)     |     |   claim_ids)     |
+------------------+     +------------------+     +--------+---------+
  retry: 2x                                                |
                              +----------------------------+
                              |
+-------------v----+     +----v-------------+     +------------------+
|  qa_validation   |     |  snapshot        |     |  publish         |
|                  +---->|                  +---->|                  |
|  Agent: qa_      |     | Agent: delta     |     | Agent: publisher |
|    validator     |     |   (deterministic)|     |   (deterministic)|
|  (deterministic) |     |                  |     |                  |
| IN:  claims      |     | IN:  claims      |     | IN:  snapshot_id |
|   doc_ids        |     |   metrics        |     |   delta_id       |
|   segment_ids    |     |                  |     |                  |
|                  |     | OUT: snapshot_id |     | OUT: publish_dir |
| OUT: gate_status |     |   delta_id       |     |   manifest       |
|   violations     |     |   delta_json     |     |   artifacts      |
|                  |     |   stability_score|     |                  |
| on_fail: claim_  |     |                  |     | end: true        |
|   extraction     |     |                  |     | version: semver  |
+------------------+     +------------------+     +------------------+
```

**Key cert-specific behavior:**
- Entity resolver also outputs `objectives` (certification objectives with codes and weights)
- Lesson composer generates modules at three depth levels (L1/L2/L3) per objective
- Question generator must ground every question to at least one `claim_id`
- QA validator checks: claim citations resolve, objectives have modules, question count is proportional to weight
- If QA fails, graph routes back to `claim_extraction` via `on_fail`

---

## Graph 2: Living Dossier

**Purpose:** Build and maintain an evolving intelligence dossier on a topic — ingest sources, extract entities/claims/metrics, detect contradictions, synthesize findings, snapshot, and publish.

**Graph file:** `graphs/dossier_graph.yaml`

```
+------------------+     +------------------+     +------------------+
|  topic_ingest    |     |  normalize       |     |  entity_         |
|                  +---->|                  +---->|  resolution      |
|                  |     |                  |     |                  |
|  Agent: ingestor |     | Agent: normalizer|     | Agent: entity_   |
|                  |     |                  |     |   resolver       |
|  IN:  sources    |     | IN:  source_     |     | IN:  normalized_ |
|                  |     |   segments       |     |   segments       |
|  OUT: doc_ids    |     | OUT: normalized_ |     | OUT: entities    |
|    segment_ids   |     |   segments       |     |   relationships  |
|    source_docs   |     |                  |     |                  |
|    source_segs   |     |                  |     |                  |
+------------------+     +------------------+     +--------+---------+
                                                           |
              +--------------------------------------------+
              |
+-------------v----+     +------------------+     +------------------+
|  claim_          |     |  metric_         |     |  contradiction_  |
|  extraction      +---->|  extraction      +---->|  check           |
|                  |     |                  |     |                  |
| Agent: claim_    |     | Agent: metric_   |     | Agent:           |
|   extractor      |     |   extractor      |     |   contradiction  |
|                  |     |                  |     |                  |
| IN:  normalized_ |     | IN:  normalized_ |     | IN:  claims      |
|   segments,      |     |   segments       |     |                  |
|   entities       |     |                  |     | OUT:             |
|                  |     | OUT: metrics     |     |   contradictions |
| OUT: claims      |     |   metric_points  |     |   updated_       |
|  (with citations)|     |                  |     |   claim_ids      |
+------------------+     +------------------+     +--------+---------+
  retry: 2x                                                |
                              +----------------------------+
                              |
+-------------v----+     +----v-------------+     +------------------+
|  snapshot        |     |  synthesis       |     |  publish         |
|                  +---->|                  +---->|                  |
| Agent: delta     |     | Agent:           |     | Agent: publisher |
|   (deterministic)|     |   synthesizer    |     |   (deterministic)|
|                  |     |                  |     |                  |
| IN:  claims      |     | IN:  claims      |     | IN:  snapshot_id |
|   metrics        |     |   metrics        |     |   delta_id       |
|                  |     |   metric_points  |     |                  |
| OUT: snapshot_id |     |   delta_json     |     | OUT: publish_dir |
|   delta_id       |     |                  |     |   manifest       |
|   delta_json     |     | OUT: synthesis   |     |   artifacts      |
|   stability_score|     |  (summary,       |     |                  |
|                  |     |   key_findings,  |     | end: true        |
|                  |     |   contradictions)|     | version: date    |
+------------------+     +------------------+     +------------------+
```

**Key dossier-specific behavior:**
- Metric extractor pulls quantitative data points (values, units, time series) from text
- Contradiction agent compares claims against each other and against `existing_claims` from prior runs
- Contradicting claims are marked `disputed` with a structured reason and severity
- Synthesizer produces a structured summary referencing only provided claims/metrics/delta
- Snapshot creates a versioned point-in-time, delta computes what changed since last run
- Date-based versioning allows daily/weekly refresh cycles

---

## Graph 3: AI Lab Observatory

**Purpose:** Benchmark AI models, extract performance metrics, analyze trends, produce routing recommendations, snapshot, and publish.

**Graph file:** `graphs/lab_graph.yaml`

```
+------------------+     +------------------+     +------------------+
|  suite_assembly  |     |  benchmark_run   |     |  scoring         |
|                  +---->|                  +---->|                  |
|                  |     |                  |     |                  |
|  Agent: ingestor |     | Agent:           |     | Agent: metric_   |
|                  |     |   synthesizer    |     |   extractor      |
|  IN:  suite_     |     | IN:  tasks       |     | IN:  normalized_ |
|    config        |     |   models         |     |   segments       |
|                  |     |                  |     |                  |
|  OUT: doc_ids    |     | OUT: synthesis   |     | OUT: metrics     |
|    segment_ids   |     |  (results,       |     |   metric_points  |
|    source_docs   |     |   scores)        |     |                  |
|    source_segs   |     |                  |     |                  |
+------------------+     +------------------+     +--------+---------+
                                                           |
              +--------------------------------------------+
              |
+-------------v----+     +------------------+     +------------------+
|  trend_metrics   |     |  routing_        |     |  snapshot        |
|                  +---->|  recommendation  +---->|                  |
|                  |     |                  |     |                  |
| Agent:           |     | Agent:           |     | Agent: delta     |
|   synthesizer    |     |   synthesizer    |     |   (deterministic)|
|                  |     |                  |     |                  |
| IN:  metrics     |     | IN:  synthesis   |     | IN:  claims      |
|   metric_points  |     |   metrics        |     |   metrics        |
|                  |     |                  |     |                  |
| OUT: synthesis   |     | OUT: synthesis   |     | OUT: snapshot_id |
|  (trend analysis)|     |  (routing_config,|     |   delta_id       |
|                  |     |   recommended    |     |   delta_json     |
|                  |     |   model per task)|     |   stability_score|
+------------------+     +------------------+     +--------+---------+
                                                           |
                                                +----------v---------+
                                                |  publish           |
                                                |                    |
                                                | Agent: publisher   |
                                                |   (deterministic)  |
                                                |                    |
                                                | IN:  snapshot_id   |
                                                |   delta_id         |
                                                |                    |
                                                | OUT: publish_dir   |
                                                |   manifest         |
                                                |   artifacts        |
                                                |                    |
                                                | end: true          |
                                                | version: suite-id  |
                                                +--------------------+
```

**Key lab-specific behavior:**
- Suite assembly ingests benchmark configuration (tasks, models, hardware spec)
- Benchmark run uses the synthesizer to produce results and scores per task/model
- Scoring extracts structured metric points (accuracy, latency, etc.)
- Trend metrics synthesizes metric trends over time
- Routing recommendation produces a `routing_config` mapping task categories to recommended models with thresholds
- The synthesizer agent is reused for three different nodes (benchmark_run, trend_metrics, routing_recommendation), each with different inputs and producing different synthesis content
- Suite-based versioning: `<suite_id>-<snapshot_hash>`

---

## Agent Inventory

| Agent | ID | LLM? | Used by |
|-------|----|------|---------|
| Ingestor | `ingestor` | yes | cert, dossier, lab |
| Normalizer | `normalizer` | yes | cert, dossier |
| Entity Resolver | `entity_resolver` | yes | cert, dossier |
| Claim Extractor | `claim_extractor` | yes | cert, dossier |
| Lesson Composer | `lesson_composer` | yes | cert only |
| Question Generator | `question_generator` | yes | cert only |
| Metric Extractor | `metric_extractor` | yes | dossier, lab |
| Contradiction | `contradiction` | yes | dossier only |
| Synthesizer | `synthesizer` | yes | dossier, lab |
| QA Validator | `qa_validator` | **no** | cert only |
| Delta | `delta` | **no** | cert, dossier, lab |
| Publisher | `publisher` | **no** | cert, dossier, lab |

---

## State Flow Summary

Each graph starts with seed data and accumulates state as it progresses:

```
Seed (sources, config)
  |
  v
[Ingest] --> doc_ids, segment_ids, source_docs, source_segments
  |
  v
[Process] --> entities, claims, metrics, modules, questions, ...
  |              (varies by graph)
  v
[Validate] --> gate_status, violations  (cert only)
  |
  v
[Snapshot] --> snapshot_id, delta_id, delta_json, stability_score
  |
  v
[Publish] --> publish_dir, manifest, artifacts
```

Every agent receives the full state dict and returns a `delta_state` dict that gets merged in. This means later agents can reference anything produced by earlier agents.

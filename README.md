# AI Swarm Platform

Unified platform that supports three product loops — **Certification Engine**, **Living Dossiers**, and **AI Lab Observatory** — using shared agents, shared data structures, shared orchestration, and shared publishing.

Includes a **Claude Premium Bridge** — a file-based task bridge between OpenClaw and Claude Code for structured, zero-API premium cognition.

Built for local-first execution with optional frontier model escalation. No heavy UI; outputs are JSON artifacts, Markdown reports, and CSV exports.

## Quick Start

```bash
pip install -e ".[dev]"

# Run the three product loops
python -m scripts.run_cert --cert_id aws-101
python -m scripts.run_dossier --topic_id healthcare-ai
python -m scripts.run_lab --suite_id bench-1

# Cron scheduler (continuous or one-shot)
python -m scripts.run_scheduler --config schedule_config.yaml
python -m scripts.run_scheduler --once

# Metrics dashboard
python -m scripts.dashboard --port 8080

# Bootstrap the automation directory structure
python -m scripts.bootstrap_automation -v

# Run tests
pytest                              # all 624 tests
pytest tests/unit/                  # unit tests only
pytest tests/integration/           # integration tests only
pytest tests/unit/test_eval.py::TestScoring  # single class
```

## Architecture

```
state dict ──► Orchestrator ──► Node 1 ──► Node 2 ──► ... ──► Publish
                   │                │          │
                   │           Agent.run()  Agent.run()
                   │                │          │
                   ▼                ▼          ▼
              YAML Graph       delta_state  delta_state
              Definition       merged into  merged into
                               run state    run state
```

### Core Components

| Component | Location | Role |
|-----------|----------|------|
| Orchestrator | `core/orchestrator.py` | Executes YAML graphs, manages state, enforces budgets, checkpoints |
| Agent Runtime | `agents/base_agent.py` | Base class + registry; agents produce `delta_state` merged into state |
| Data Layer | `data/` | SQLite (23 tables) + filesystem; DAOs per domain object |
| QA Gate | `agents/qa_validator_agent.py` | Global + domain-specific validation rules |
| Delta Engine | `agents/delta_agent.py` | Snapshot hashing + structured claim diffs |
| Publisher | `agents/publisher_agent.py` + `publish/renderer.py` | JSON/Markdown/CSV artifacts to `publish/out/` |
| Routing | `core/routing.py` | Local-first model selection with escalation criteria |
| Budgets | `core/budgets.py` | Per-node/run token+cost caps, degradation, human review flags |
| Observability | `core/logging.py` | Structured JSON logging, API key redaction, metrics collector |
| Scheduler | `core/scheduler.py` | Cron-based loop execution with configurable schedules |
| Notifications | `core/notifications.py` | Email (stub) + webhook hooks on run completion/failure |
| Dashboard | `scripts/dashboard.py` | HTTP JSON endpoints for metrics and run history |
| Automation Bridge | `automation/` | File-based task bridge: config, queue state, task schema, validation |

### Three Graph Loops

**Certification** (9 nodes): ingest blueprint → resolve objectives → normalize → extract claims → compose lessons → generate questions → QA validate → snapshot → publish

**Dossier** (9 nodes): ingest topic → normalize → resolve entities → extract claims → extract metrics → detect contradictions → snapshot → synthesize → publish

**Lab** (7 nodes): assemble suite → benchmark run → score → trend metrics → routing recommendation → snapshot → publish

### Agents

| Agent | ID | LLM? | Purpose |
|-------|----|------|---------|
| Ingestor | `ingestor` | Yes | Fetch + segment sources |
| Normalizer | `normalizer` | Yes | Clean text to consistent format |
| Entity Resolver | `entity_resolver` | Yes | Extract + deduplicate entities |
| Claim Extractor | `claim_extractor` | Yes | Extract atomic cited claims |
| Metric Extractor | `metric_extractor` | Yes | Extract quantitative metrics |
| Contradiction | `contradiction` | Yes | Detect conflicting claims |
| Synthesizer | `synthesizer` | Yes | Produce constrained synthesis |
| Lesson Composer | `lesson_composer` | Yes | L1/L2/L3 lesson modules |
| Question Generator | `question_generator` | Yes | Question bank per objective |
| QA Validator | `qa_validator` | No | Deterministic gate rules |
| Delta | `delta` | No | Snapshot hash + structured diff |
| Publisher | `publisher` | No | Render + package artifacts |

### Versioning

- **Certification**: semver (`1.0.0` → `1.1.0`)
- **Dossier**: date-based (`2026-02-16`)
- **Lab**: suite + snapshot hash (`bench-1-abc12345`)

## Claude Premium Bridge

A file-based automation bridge between OpenClaw and Claude Code. OpenClaw writes structured markdown task files; Claude Code processes them via slash command and writes structured result files. Zero Anthropic API usage required.

### Workflow

```
OpenClaw → Task File (.md) → Claude Code (slash command) → Result File (.result.md) → OpenClaw
```

### Directory Layout

```
automation/
  config.yaml          configuration (paths, validation, watcher)
  config.py            AutomationConfig dataclass + load_config()
  queue.py             QueueState with atomic JSON persistence
  task_schema.py       TaskHeader/TaskFile dataclasses + parser + ID generator
  validator.py         validate_task() and validate_result()
  queue.json           runtime queue state (created by bootstrap)
  tasks/               new tasks written by OpenClaw
  processing/          tasks currently being handled
  outputs/             Claude result files
  archive/             completed tasks
  schemas/             task_template.md + result_template.md
  logs/                structured log files
```

### Task File Format

Task files use markdown headers for metadata and `## SECTION` blocks for content:

```markdown
# TASK_ID: 2026-02-17-001
# MODE: FAST | BALANCED | PREMIUM
# TASK_TYPE: ARCHITECTURE | REFACTOR | ANALYSIS | DESIGN | REVIEW
# PRIORITY: LOW | MEDIUM | HIGH
# OUTPUT_FORMAT: MARKDOWN | JSON | TEXT
# CREATED_AT: 2026-02-17T10:00:00
# PARENT_TASK: 2026-02-16-005    (optional, for chained tasks)

## CONTEXT
## CONSTRAINTS
## DELIVERABLE
## SUCCESS CRITERIA
```

### Result File Format

```markdown
# RESULT_FOR: 2026-02-17-001
# STATUS: COMPLETE | FAILED
# QUALITY_LEVEL: LOW | MEDIUM | HIGH
# COMPLETED_AT: 2026-02-17T12:00:00

## OUTPUT          (required if COMPLETE)
## ERROR           (required if FAILED)
## META
### Assumptions
### Risks
### Suggested_Followups
```

### Queue State

Task IDs transition through: `pending → processing → completed | failed`. State is persisted atomically to `queue.json` (write-tmp-then-rename). Supports parent linkage for chained multi-stage tasks.

### Bootstrap

```bash
# Create all automation directories and initialize queue.json
python -m scripts.bootstrap_automation -v

# With custom config
python -m scripts.bootstrap_automation --config path/to/config.yaml -v
```

## Project Structure

```
agents/          12 agent modules + base class + registry
automation/      Claude Premium Bridge: config, queue, task schema, validator, templates
core/            orchestrator, state, routing, budgets, errors, logging, scheduler, notifications
connectors/      web_fetch, rss_fetch, file_loader
data/            schema.sql + db.py + 7 DAO modules (incl. telemetry)
eval/            rubrics (6 built-in), lab_tasks, scoring engine
graphs/          3 YAML graph definitions
publish/         renderer (Markdown/CSV) + out/ (gitignored)
scripts/         6 CLI entrypoints (cert, dossier, lab, scheduler, dashboard, bootstrap)
tests/           624 tests (unit + integration)
```

## Configuration

Graphs are defined in YAML (`graphs/*.yaml`). Each node specifies:

```yaml
node_name:
  agent: registry_key
  inputs: [state_keys_required]
  outputs: [state_keys_produced]
  next: next_node
  on_fail: fallback_node      # optional
  retry:                       # optional
    max_attempts: 2
    backoff_seconds: 1.0
  budget:                      # optional
    max_tokens: 10000
    max_cost: 0.50
  end: true                    # marks terminal node
```

## Local Models

The platform is designed for local-first execution. Models `deepseek-r1:1.5b` and `qwen2.5:7b` are the target local models. Frontier escalation triggers when: confidence is low, citations are missing, contradiction ambiguity is high, or synthesis complexity exceeds threshold.

## License

Private repository.

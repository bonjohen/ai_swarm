# Claude Premium Bridge — Phased Implementation Plan

All items below are derived from `docs/claude_premium_bridge_pdr.md`. Each phase is ordered by dependency — complete earlier phases before starting later ones.

Set the checkbox to [~] while you are working on it, and to [X] when complete.

**Key design decisions:**
- File-based task bridge between OpenClaw and Claude Code — zero API usage.
- Markdown task files with structured headers and sections.
- Queue state tracked in `queue.json` with deterministic transitions.
- Python CLI for task management; watcher service for output polling.
- Standard library preferred; pydantic only if strongly justified.
- All paths relative to `automation/` base directory.

---

## Phase B0: Directory Structure and Configuration

Bootstrap the directory layout, config file, and queue state file.

### B0.1 Directory Bootstrap

- [X] Create `automation/` base directory structure:
  - `automation/tasks/` — new tasks written by OpenClaw
  - `automation/processing/` — tasks currently being handled
  - `automation/outputs/` — Claude results
  - `automation/archive/` — completed tasks
  - `automation/schemas/` — reusable prompt templates
  - `automation/logs/` — structured log files
- [X] Create `scripts/bootstrap_automation.py` — idempotent script that creates all directories and initializes empty files

### B0.2 Configuration File

- [X] Create `automation/config.yaml`:
  - `paths.base`: `automation`
  - `paths.tasks`: `automation/tasks`
  - `paths.processing`: `automation/processing`
  - `paths.outputs`: `automation/outputs`
  - `paths.archive`: `automation/archive`
  - `paths.logs`: `automation/logs`
  - `validation.require_meta`: `true`
  - `validation.require_success_criteria`: `true`
  - `watcher.interval_seconds`: `5`
- [X] Implement `automation/config.py` — `load_config(path) -> AutomationConfig` dataclass

### B0.3 Queue State File

- [X] Create `automation/queue.json` with initial structure:
  ```json
  {"pending": [], "processing": [], "completed": [], "failed": []}
  ```
- [X] Implement `automation/queue.py`:
  - `load_queue(path) -> QueueState`
  - `save_queue(path, state)` — atomic write (write tmp then rename)
  - `add_pending(state, task_id)`
  - `move_to_processing(state, task_id)`
  - `move_to_completed(state, task_id)`
  - `move_to_failed(state, task_id)`
  - `link_parent(state, task_id, parent_id)` — for chained tasks (Section 13)

### B0.4 Phase B0 Tests

- [X] Test bootstrap script creates all directories idempotently
- [X] Test `load_config()` parses config.yaml correctly
- [X] Test `load_queue()` / `save_queue()` round-trip
- [X] Test queue state transitions: pending → processing → completed
- [X] Test queue state transitions: pending → processing → failed
- [X] Test atomic write (no corruption on concurrent access)

---

## Phase B1: Task File Specification and Validation

Define task file format, create validator, and build example templates.

### B1.1 Task File Schema

- [X] Implement `automation/task_schema.py`:
  - `TaskHeader` dataclass:
    - `task_id: str` — format `YYYY-MM-DD-###`
    - `mode: str` — `FAST | BALANCED | PREMIUM`
    - `task_type: str` — `ARCHITECTURE | REFACTOR | ANALYSIS | DESIGN | REVIEW`
    - `priority: str` — `LOW | MEDIUM | HIGH`
    - `output_format: str` — `MARKDOWN | JSON | TEXT`
    - `created_at: str` — ISO8601
    - `parent_task: str | None` — optional, for chained tasks
  - `TaskFile` dataclass:
    - `header: TaskHeader`
    - `context: str`
    - `constraints: str`
    - `deliverable: str`
    - `success_criteria: str`
- [X] Implement `parse_task_file(path) -> TaskFile` — parse markdown headers and sections
- [X] Implement `generate_task_id() -> str` — auto-increment `YYYY-MM-DD-###` based on existing tasks

### B1.2 Validator

- [X] Implement `automation/validator.py`:
  - `validate_task(path) -> list[ValidationError]`:
    - TASK_ID present and matches filename
    - All required headers present (MODE, TASK_TYPE, PRIORITY, OUTPUT_FORMAT, CREATED_AT)
    - All required sections present (CONTEXT, CONSTRAINTS, DELIVERABLE, SUCCESS_CRITERIA)
    - MODE value in allowed set
    - TASK_TYPE value in allowed set
    - PRIORITY value in allowed set
    - OUTPUT_FORMAT value in allowed set
    - CREATED_AT is valid ISO8601
  - `validate_result(path) -> list[ValidationError]`:
    - RESULT_FOR present and matches a known task
    - STATUS present and in `{COMPLETE, FAILED}`
    - QUALITY_LEVEL present and in `{LOW, MEDIUM, HIGH}`
    - COMPLETED_AT is valid ISO8601
    - OUTPUT section present and non-empty (if STATUS == COMPLETE)
    - ERROR section present (if STATUS == FAILED)
    - META section present with Assumptions, Risks, Suggested_Followups
  - `ValidationError` dataclass: `field: str`, `message: str`, `severity: str`

### B1.3 Templates

- [X] Create `automation/schemas/task_template.md` — example task file with all required headers/sections
- [X] Create `automation/schemas/result_template.md` — example result file with all required headers/sections

### B1.4 Phase B1 Tests

- [X] Test `parse_task_file()` with valid task file
- [X] Test `parse_task_file()` with missing headers raises errors
- [X] Test `parse_task_file()` with missing sections raises errors
- [X] Test `validate_task()` returns no errors for valid file
- [X] Test `validate_task()` catches TASK_ID / filename mismatch
- [X] Test `validate_task()` catches invalid MODE, TASK_TYPE, PRIORITY values
- [X] Test `validate_result()` with valid COMPLETE result
- [X] Test `validate_result()` with valid FAILED result (ERROR section present)
- [X] Test `validate_result()` catches missing OUTPUT section
- [X] Test `generate_task_id()` auto-increments correctly

---

## Phase B2: Automation CLI

Build the CLI tool for task creation, listing, validation, and archiving.

### B2.1 CLI Framework

- [X] Implement `automation/automation_cli.py` using argparse:
  - Subcommands: `create`, `list`, `validate`, `archive`, `status`
  - Global options: `--config` (path to config.yaml), `-v` (verbose)

### B2.2 Create Command

- [X] `python automation_cli.py create --type <TASK_TYPE> --mode <MODE> --title "<title>" [--priority <PRIORITY>] [--format <OUTPUT_FORMAT>] [--parent <TASK_ID>]`:
  - Generate TASK_ID via `generate_task_id()`
  - Create task file from template with populated headers
  - Add CONTEXT, CONSTRAINTS, DELIVERABLE, SUCCESS_CRITERIA sections (placeholder text)
  - Write to `automation/tasks/<TASK_ID>.md`
  - Update queue.json: add to `pending`
  - Print created file path and TASK_ID

### B2.3 List Command

- [X] `python automation_cli.py list [--status pending|processing|completed|failed] [--all]`:
  - Read queue.json
  - Display task IDs grouped by status
  - Show task type, mode, priority, created_at for each

### B2.4 Validate Command

- [X] `python automation_cli.py validate <TASK_ID>`:
  - Find result file in `automation/outputs/<TASK_ID>.result.md`
  - Run `validate_result()` on it
  - Print validation results (pass/fail with details)
  - Return exit code 0 on pass, 1 on fail

### B2.5 Archive Command

- [X] `python automation_cli.py archive <TASK_ID>`:
  - Move task file from current location to `automation/archive/`
  - Update queue.json accordingly
  - Print confirmation

### B2.6 Status Command

- [X] `python automation_cli.py status`:
  - Read queue.json
  - Print counts: pending, processing, completed, failed
  - Print dependency chain for any tasks with PARENT_TASK

### B2.7 Phase B2 Tests

- [X] Test `create` generates valid task file with correct headers
- [X] Test `create` updates queue.json
- [X] Test `create --parent` links parent task
- [X] Test `list` shows tasks grouped by status
- [X] Test `list --status pending` filters correctly
- [X] Test `validate` passes for valid result file
- [X] Test `validate` fails for malformed result file
- [X] Test `archive` moves file and updates queue
- [X] Test `status` shows correct counts

---

## Phase B3: Claude Processing Workflow

Implement the task processing flow that Claude Code executes via slash command.

### B3.1 Task Processor

- [ ] Implement `automation/processor.py`:
  - `pick_next_task(config) -> TaskFile | None` — get highest-priority pending task
  - `start_processing(config, task_id)`:
    - Move file from `tasks/` to `processing/`
    - Update queue.json: move to `processing`
  - `complete_processing(config, task_id, result_content)`:
    - Write result file to `outputs/<TASK_ID>.result.md`
    - Validate result file
    - Move original task to `archive/`
    - Update queue.json: move to `completed`
  - `fail_processing(config, task_id, error_reason)`:
    - Write result file with STATUS: FAILED and ERROR section
    - Move original task to `archive/`
    - Update queue.json: move to `failed`

### B3.2 Result File Writer

- [ ] Implement `automation/result_writer.py`:
  - `write_result(task_id, status, quality_level, output, meta, error=None) -> Path`:
    - Generate proper headers (RESULT_FOR, STATUS, QUALITY_LEVEL, COMPLETED_AT)
    - Write OUTPUT section
    - Write META section (Assumptions, Risks, Suggested_Followups)
    - If FAILED: write ERROR section
    - Validate before writing

### B3.3 Phase B3 Tests

- [ ] Test `pick_next_task()` returns highest priority pending task
- [ ] Test `start_processing()` moves file and updates queue
- [ ] Test `complete_processing()` writes valid result and archives task
- [ ] Test `fail_processing()` writes FAILED result with ERROR section
- [ ] Test `write_result()` produces valid result file
- [ ] Test full lifecycle: create → process → complete → archive

---

## Phase B4: Watcher Service

Implement the polling watcher that monitors outputs and updates state.

### B4.1 Watcher Implementation

- [ ] Implement `automation/watcher.py`:
  - `watch(config)` — continuous polling loop:
    - Poll `automation/outputs/` for new `.result.md` files
    - For each new result file:
      - Validate with `validate_result()`
      - If valid: update queue.json to `completed`
      - If invalid: update queue.json to `failed`, log structured error
    - Sleep for `config.watcher.interval_seconds`
  - `watch_once(config)` — single poll cycle (for testing)
  - CLI: `python watcher.py [--config config.yaml] [--once]`

### B4.2 Phase B4 Tests

- [ ] Test `watch_once()` detects new result file and updates queue
- [ ] Test `watch_once()` validates result and marks failed on validation error
- [ ] Test `watch_once()` ignores already-processed results
- [ ] Test watcher logs structured entries to `automation/logs/system.log`

---

## Phase B5: Structured Logging

Add structured logging throughout the system.

### B5.1 Log System

- [ ] Implement `automation/logging.py`:
  - Structured JSON log entries to `automation/logs/system.log`
  - Each entry: `timestamp`, `task_id`, `action`, `status`, `details`
  - Actions: `task_created`, `task_processing`, `task_completed`, `task_failed`, `task_archived`, `validation_passed`, `validation_failed`, `watcher_poll`
- [ ] Wire logging into all modules: CLI, processor, watcher, validator

### B5.2 Phase B5 Tests

- [ ] Test log entries written with correct structure
- [ ] Test all actions produce log entries
- [ ] Test log file rotation (or verify file doesn't grow unbounded for now)

---

## Phase B6: Error Handling and Hardening

Deterministic error handling for all failure modes.

### B6.1 Error Handling

- [ ] Handle malformed result files: mark FAILED, log structured error
- [ ] Handle header mismatch (RESULT_FOR doesn't match any known task): log error, skip
- [ ] Handle missing sections: validation catches and reports each missing section
- [ ] Handle STATUS != COMPLETE and STATUS != FAILED: treat as malformed
- [ ] Handle file move failures (permissions, missing directories): log and retry once
- [ ] Handle queue.json corruption: detect and rebuild from filesystem state

### B6.2 Phase B6 Tests

- [ ] Test malformed result file triggers FAILED status
- [ ] Test header mismatch is logged and skipped
- [ ] Test queue.json rebuild from filesystem state
- [ ] Test file move retry on transient failure
- [ ] Test concurrent CLI access doesn't corrupt queue.json

---

## Open Decisions

| Decision | Default | Notes |
|----------|---------|-------|
| Automation base path | `automation/` | Relative to project root |
| Task ID format | `YYYY-MM-DD-###` | Daily sequence number |
| Queue persistence | `queue.json` (atomic write) | Could use SQLite later |
| Logging format | JSON lines to `system.log` | One JSON object per line |
| Dependency framework | Standard library only | argparse for CLI, pathlib for paths, json for state |
| Pydantic usage | Avoid unless strongly justified | Use dataclasses instead |
| Watcher polling interval | 5 seconds | Configurable in config.yaml |
| File locking | Atomic rename (no explicit locks) | Sufficient for single-user |

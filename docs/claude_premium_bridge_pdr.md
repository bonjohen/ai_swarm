```markdown
# PDR.md  
# Claude Premium Bridge — File-Based Trigger System  
Version: 1.0  
Owner: John Boen  
Target Consumer: Claude Code  

---

# 1. Purpose

Design and implement a structured, file-based automation bridge between OpenClaw and Claude Code.

The system must:

- Allow OpenClaw to generate structured task files
- Allow Claude Code to process tasks via slash command
- Produce structured result files
- Enable automated ingestion and validation
- Require zero Anthropic API usage
- Be deterministic and production-ready

Claude Code will implement the code described in this document.

---

# 2. System Overview

This system establishes a semi-automated workflow:

OpenClaw → Task File → Claude Code (manual slash command) → Result File → OpenClaw

Claude Code acts as a premium cognition module, manually triggered but structurally integrated.

---

# 3. Directory Structure

Claude Code must implement the following directory layout:

```

/automation/
/tasks/
/processing/
/outputs/
/archive/
/schemas/
queue.json

```

## Folder Roles

- tasks → new tasks written by OpenClaw
- processing → tasks currently being handled
- outputs → Claude results
- archive → completed tasks
- schemas → reusable prompt templates
- queue.json → system state registry

---

# 4. Task File Specification

Task files are Markdown documents with structured headers.

Filename format:

```

<TASK_ID>.md

```

TASK_ID format:

```

YYYY-MM-DD-###

```

Example:

```

2026-02-16-001.md

```

---

## 4.1 Required Header Format

Each task file must contain:

```

# TASK_ID: <ID>

# MODE: FAST | BALANCED | PREMIUM

# TASK_TYPE: ARCHITECTURE | REFACTOR | ANALYSIS | DESIGN | REVIEW

# PRIORITY: LOW | MEDIUM | HIGH

# OUTPUT_FORMAT: MARKDOWN | JSON | TEXT

# CREATED_AT: ISO8601

```

---

## 4.2 Required Sections

```

## CONTEXT

<background>

## CONSTRAINTS

<rules>

## DELIVERABLE

<exact output requested>

## SUCCESS_CRITERIA

<validation conditions>
```

---

# 5. Claude Processing Rules

Claude Code must:

1. Move task from `/tasks/` → `/processing/`
2. Generate result
3. Write result to:

```
/automation/outputs/<TASK_ID>.result.md
```

4. Move original task to `/archive/`

---

# 6. Result File Specification

Result filename:

```
<TASK_ID>.result.md
```

Required header:

```
# RESULT_FOR: <TASK_ID>
# STATUS: COMPLETE | FAILED
# QUALITY_LEVEL: LOW | MEDIUM | HIGH
# COMPLETED_AT: ISO8601
```

Required sections:

```
## OUTPUT
<deliverable>

## META
### Assumptions
### Risks
### Suggested_Followups
```

If STATUS == FAILED:

```
## ERROR
<reason>
```

---

# 7. Queue System

Claude Code must implement a `queue.json` file.

Structure:

```json
{
  "pending": [],
  "processing": [],
  "completed": [],
  "failed": []
}
```

This file must be updated when:

* Task created
* Task moved to processing
* Result completed
* Task archived

---

# 8. Automation Manager (Python CLI)

Claude Code must generate a Python CLI tool:

```
automation_cli.py
```

Capabilities:

### Commands

Create task:

```
python automation_cli.py create --type ARCHITECTURE --mode PREMIUM --title "Refactor router"
```

List tasks:

```
python automation_cli.py list
```

Validate outputs:

```
python automation_cli.py validate <TASK_ID>
```

Archive manually:

```
python automation_cli.py archive <TASK_ID>
```

---

# 9. Validation Rules

Validator must check:

* TASK_ID consistency
* Required headers present
* Required sections present
* STATUS field exists
* OUTPUT section non-empty
* Filename matches header ID

Validation failure must return structured error.

---

# 10. Watcher Service

Claude Code must generate:

```
watcher.py
```

Behavior:

* Poll `/automation/outputs`
* Validate new result files
* Update queue.json
* Log status

Polling interval: 5 seconds (configurable)

---

# 11. Config File

Create:

```
config.yaml
```

Example:

```yaml
paths:
  base: automation
  tasks: automation/tasks
  processing: automation/processing
  outputs: automation/outputs
  archive: automation/archive

validation:
  require_meta: true
  require_success_criteria: true

watcher:
  interval_seconds: 5
```

---

# 12. Error Handling Requirements

If:

* Result file malformed
* Header mismatch
* Missing sections
* STATUS != COMPLETE

Then:

* Mark as FAILED in queue.json
* Move task to archive
* Log structured error

---

# 13. Multi-Stage Processing Support

Support chained tasks.

If task contains:

```
# PARENT_TASK: <ID>
```

Then:

* Link in queue.json
* Preserve dependency chain

---

# 14. Logging

Use structured logging.

Log file:

```
automation/logs/system.log
```

Each log entry must include:

* timestamp
* task_id
* action
* status

---

# 15. Non-Goals

Do not:

* Use Anthropic API
* Use external services
* Implement UI automation
* Create web server
* Add unnecessary frameworks

Keep implementation minimal and deterministic.

---

# 16. Implementation Constraints

* Python 3.11+
* Standard library preferred
* Use pydantic only if strongly justified
* Avoid heavy dependencies
* Code must be clean and modular

---

# 17. Acceptance Criteria

System is complete when:

* Task can be created via CLI
* Claude can process via slash command
* Result is validated
* Queue updates correctly
* Task archived automatically
* Errors handled deterministically

---

# 18. Deliverables From Claude Code

Claude Code must generate:

1. automation_cli.py
2. watcher.py
3. validator.py
4. config.yaml
5. queue.json initializer
6. Directory bootstrap script
7. README.md for usage
8. Example task template
9. Example schema template

All files must be production-quality and runnable.

---

# 19. Future Extensions (Do Not Implement Now)

* Web dashboard
* Parallel queue
* Multi-user system
* Remote sync
* OpenClaw API integration
* Vector memory integration

---

# 20. Final Instruction to Claude Code

Implement this system exactly as specified.

Do not redesign architecture.

Do not introduce unnecessary abstractions.

Focus on:

* Determinism
* Validation
* File integrity
* Clear state transitions
* Clean Python code

End of PDR.

```
```

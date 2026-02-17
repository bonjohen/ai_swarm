# Story World Persistent Memory System — Phased Implementation Plan

All items below are derived from `docs/persistent_memory_story_system_prd.md`. Each phase is ordered by dependency — complete earlier phases before starting later ones.

---

## Phase S0: Schema and Data Layer

Extend the data layer with story-domain tables and DAOs. No agents or graph yet — just the foundation.

### S0.1 Schema Extension

- [x] Add `story_worlds` table to `data/schema.sql`:
  - `world_id TEXT PK, name TEXT, genre TEXT, tone TEXT, setting_json TEXT, thematic_constraints_json TEXT, audience_profile_json TEXT, current_episode_number INTEGER, current_timeline_position TEXT, created_at TEXT, updated_at TEXT`
- [x] Add `characters` table to `data/schema.sql`:
  - `character_id TEXT PK, world_id TEXT, name TEXT, role TEXT, arc_stage TEXT, alive INTEGER, traits_json TEXT, goals_json TEXT, fears_json TEXT, beliefs_json TEXT, voice_notes TEXT, meta_json TEXT`
- [x] Add `narrative_threads` table to `data/schema.sql`:
  - `thread_id TEXT PK, world_id TEXT, title TEXT, status TEXT, introduced_in_episode INTEGER, resolved_in_episode INTEGER, thematic_tag TEXT, related_character_ids_json TEXT, escalation_points_json TEXT, meta_json TEXT`
- [x] Add `episodes` table to `data/schema.sql`:
  - `episode_id TEXT PK, world_id TEXT, episode_number INTEGER, title TEXT, act_structure_json TEXT, scene_count INTEGER, word_count INTEGER, tension_curve_json TEXT, snapshot_id TEXT, run_id TEXT, status TEXT, created_at TEXT, meta_json TEXT`

### S0.2 DAOs

- [x] Implement `data/dao_story_worlds.py` — CRUD for story_worlds: `insert_world()`, `get_world()`, `update_world()`, `increment_episode_number()`
- [x] Implement `data/dao_characters.py` — CRUD for characters: `insert_character()`, `get_characters_for_world()`, `update_character()`, `update_arc_stage()`
- [x] Implement `data/dao_threads.py` — CRUD for narrative_threads: `insert_thread()`, `get_open_threads()`, `get_threads_for_world()`, `resolve_thread()`, `add_escalation_point()`
- [x] Implement `data/dao_episodes.py` — CRUD for episodes: `insert_episode()`, `get_episodes_for_world()`, `get_latest_episode()`, `update_episode_status()`

### S0.3 Phase S0 Tests

- [x] DAO round-trip tests for each new DAO module (insert, read, update)
- [x] Schema migration test: verify `get_initialized_connection()` creates new tables alongside existing ones
- [x] Test audience_profile_json serialization/deserialization
- [x] Test thread lifecycle: open -> escalating -> climax -> resolved
- [x] Test character arc_stage transitions: introduction -> rising -> crisis -> resolution -> transformed

---

## Phase S1: Story-Domain Agents

Build all 6 new story-specific agents with parse/validate methods. No graph wiring yet — agents tested individually.

### S1.1 StoryMemoryLoaderAgent (Deterministic)

- [x] Implement `agents/story_memory_loader_agent.py`
  - Override `run()` (no LLM call — deterministic)
  - Load world config from `story_worlds` table
  - Load characters from `characters` table
  - Load open threads from `narrative_threads` table
  - Load previous snapshot via `get_latest_snapshot(conn, "story", world_id)`
  - Load existing claims for scope `("story", world_id)`
  - Compute next episode number
  - Extract audience_profile from world config
  - Output state keys: `world_state`, `characters`, `active_threads`, `previous_snapshot`, `existing_claims`, `episode_number`, `audience_profile`, `world_id`

### S1.2 PremiseArchitectAgent

- [x] Implement `agents/premise_architect_agent.py`
  - SYSTEM_PROMPT: generate premise aligned to world, audience, open threads
  - USER_TEMPLATE: includes `{world_state}`, `{characters}`, `{active_threads}`, `{audience_profile}`
  - Output schema: `premise` (str), `episode_title` (str), `selected_threads` (list of thread_ids)
  - Validation: premise is non-empty, at least one thread selected (or new thread if none exist), episode_title is non-empty
  - POLICY: local model, max_tokens 2048

### S1.3 PlotArchitectAgent

- [x] Implement `agents/plot_architect_agent.py`
  - SYSTEM_PROMPT: generate structured outline — acts, scenes, character conflicts, thread escalation. No prose.
  - USER_TEMPLATE: includes `{premise}`, `{characters}`, `{active_threads}`, `{selected_threads}`, `{audience_profile}`
  - Output schema: `act_structure` (list of act objects), `scene_plans` (list of scene plan objects with scene_id, act, pov_character, conflict, objective, stakes, emotional_arc)
  - Validation: scene count within audience profile target, every POV character exists in characters list, each act has at least one scene
  - POLICY: local model, max_tokens 4096

### S1.4 SceneWriterAgent

- [x] Implement `agents/scene_writer_agent.py`
  - SYSTEM_PROMPT: generate prose for all planned scenes, respecting audience profile, character voices, world rules
  - USER_TEMPLATE: includes `{act_structure}`, `{scene_plans}`, `{characters}`, `{world_state}`, `{audience_profile}`, `{violations}` (empty on first pass, populated on retry)
  - Output schema: `scenes` (list of {scene_id, text, word_count}), `episode_text` (str — full concatenated text)
  - Validation: every scene_id from scene_plans is present, total word_count > 0, episode_text is non-empty
  - POLICY: local model with frontier escalation on retry, max_tokens 8192

### S1.5 CanonUpdaterAgent

- [x] Implement `agents/canon_updater_agent.py`
  - SYSTEM_PROMPT: extract canonical changes from scenes — new facts, character changes, thread updates, new entities
  - USER_TEMPLATE: includes `{scenes}`, `{characters}`, `{world_state}`, `{existing_claims}`
  - Output schema: `new_claims` (list of claim objects with claim_type in [canon_fact, world_rule, character_trait, event]), `updated_characters` (list of character delta objects), `new_threads` (list), `resolved_threads` (list of thread_ids), `new_entities` (list)
  - Validation: every new claim has citations (doc_id + segment_id referencing episode/scene), claim_type is valid
  - POLICY: local model, max_tokens 4096

### S1.6 AudienceComplianceAgent

- [x] Implement `agents/audience_compliance_agent.py`
  - SYSTEM_PROMPT: validate episode text against audience profile constraints
  - USER_TEMPLATE: includes `{episode_text}`, `{audience_profile}`
  - Output schema: `compliance_status` ("PASS" or "FAIL"), `compliance_violations` (list of {rule, detail, scene_id})
  - Validation: compliance_status is "PASS" or "FAIL", violations is a list
  - POLICY: local model, max_tokens 4096

### S1.7 NarrationFormatterAgent

- [x] Implement `agents/narration_formatter_agent.py`
  - SYSTEM_PROMPT: convert episode text to read-aloud format with stage directions, pause markers, emphasis, character voice tags; generate "previously on" recap from delta
  - USER_TEMPLATE: includes `{episode_text}`, `{characters}`, `{episode_title}`, `{delta_json}`
  - Output schema: `narration_script` (str), `recap` (str)
  - Validation: narration_script is non-empty, recap is non-empty
  - POLICY: local model, max_tokens 8192

### S1.8 Phase S1 Tests

- [x] Unit tests for each new agent's parse/validate with sample JSON responses
- [x] StoryMemoryLoaderAgent test: loads from pre-populated DB, produces correct state keys
- [x] PremiseArchitectAgent: validates thread selection, rejects empty premise
- [x] PlotArchitectAgent: validates scene count bounds, POV character existence
- [x] SceneWriterAgent: validates all scene_ids present in output
- [x] CanonUpdaterAgent: validates claim citations, claim_type values
- [x] AudienceComplianceAgent: validates PASS/FAIL output, violation format
- [x] NarrationFormatterAgent: validates non-empty outputs

---

## Phase S2: Graph and CLI

Wire the agents into a graph and create the CLI entrypoint.

### S2.1 Story Graph

- [x] Write `graphs/story_graph.yaml` — 11-node chain:
  1. `world_memory_load` (story_memory_loader)
  2. `premise` (premise_architect)
  3. `plot` (plot_architect)
  4. `scene_writing` (scene_writer)
  5. `canon_update` (canon_updater)
  6. `contradiction_check` (contradiction) — retry: 2x
  7. `audience_check` (audience_compliance)
  8. `qa_validation` (qa_validator) — on_fail: scene_writing
  9. `snapshot` (delta)
  10. `narration` (narration_formatter)
  11. `publish` (publisher) — end: true

### S2.2 Story-Domain QA Rules

- [x] Extend `agents/qa_validator_agent.py` with story-domain gate rules:
  - Canon integrity: every new claim cites an episode_id and scene_id
  - Character consistency: referenced characters exist, arc_stage transitions are valid
  - Thread tracking: at least one thread advanced per episode, resolved threads had escalation
  - Audience compliance: compliance_status == "PASS"
  - Structural integrity: >= 2 scenes, every scene has POV character

### S2.3 CLI and Script

- [x] Implement `scripts/run_story.py` — CLI entrypoint:
  - `python -m scripts.run_story --world_id <id> [--sources <seed_json>] [--db <path>] [--model-call <mode>] [-v]`
  - On first run with `--sources`: create world, characters, initial threads from seed JSON
  - On subsequent runs: StoryMemoryLoaderAgent loads state from DB
  - Register all agents (6 story + 4 reused: contradiction, qa_validator, delta, publisher)
  - Execute graph, write episode record, update world state in DB

### S2.4 Seed Data

- [x] Create `examples/story_seed.json` — minimal world config:
  - 1 world (fantasy genre, whimsical tone)
  - 2 characters (protagonist + supporting)
  - Audience profile (age 8-12, intermediate vocabulary, mild violence)
  - 1 initial thread

### S2.5 Phase S2 Tests

- [x] Integration test: story graph end-to-end with mock model responses
  - Fixture: 1 world, 2 characters, 1 open thread, 3-scene episode
  - Verify: all 11 nodes execute successfully
  - Verify: episode produced, claims extracted, snapshot created, artifacts published
- [x] Integration test: multi-episode continuity
  - Run 2 consecutive episodes for the same world with mock responses
  - Verify: second run loads state from first run
  - Verify: delta report shows changes between episodes
  - ~Verify: character arc_stage progressed~ (deferred to S4 — requires post-run DB persistence)
  - ~Verify: thread escalation tracked~ (deferred to S4 — requires post-run DB persistence)
- [x] QA gate tests: each story-domain rule (pass and fail cases)

---

## Phase S3: Publishing and Output

Extend the publisher to handle story-domain artifacts.

### S3.1 Story Publisher Support

- [x] Extend `agents/publisher_agent.py` to handle `scope_type = "story"`:
  - Version label: `E<number>` (e.g., `E001`)
  - Produce: `episode.json`, `episode.md`, `narration_script.txt`, `recap.md`, `delta_json.json`, `world_state.json`
- [x] Extend `publish/renderer.py` with story templates:
  - Episode Markdown: title, scenes with headers, word count footer
  - World state JSON: current characters, active threads, claim summary
  - Recap Markdown: "Previously on..." narrative summary

### S3.2 Episode Versioning

- [x] Implement episode-number versioning in `publisher_agent.py`:
  - `auto_version()` for `scope_type = "story"` returns `E<zero-padded episode_number>`
  - Published to `publish/out/story/<world_id>/E001/`, `E002/`, etc.

### S3.3 Phase S3 Tests

- [x] Golden test: story publish output matches expected artifact structure
- [x] Manifest.json schema validation for story publishes
- [x] Artifacts.json integrity: all listed paths exist, hashes match
- [x] Episode.md readable format test
- [x] Multi-episode publish: E001 and E002 in separate version directories

---

## Phase S4: Hardening and Polish

Robustness improvements specific to the story system.

### S4.1 World State Persistence

- [x] After successful graph run in `run_story.py`:
  - Write new claims to DB via `dao_claims`
  - Update characters in DB via `dao_characters` (arc_stage, beliefs, goals from `updated_characters`)
  - Insert/resolve threads in DB via `dao_threads` (from `new_threads`, `resolved_threads`)
  - Insert episode record via `dao_episodes`
  - Increment `current_episode_number` in `story_worlds`
  - Insert new entities via `dao_entities`

### S4.2 Frontier Escalation for Scene Writing

- [x] Configure scene_writer POLICY for frontier escalation:
  - Escalate when: audience compliance fails on retry, or QA gate fails on scene_writing retry
  - Log escalation decision to run_events

### S4.3 Budget Enforcement

- [x] Set story-specific budget defaults in graph YAML:
  - Per-node caps: scene_writer 8192 tokens, narration_formatter 8192 tokens, other agents 4096
  - Per-run cap: 32768 tokens total
  - Degradation: reduce scene count, simplify prose, skip narration formatting

### S4.4 Character Arc Validation

- [x] Implement arc_stage transition enforcement in dao_characters:
  - Allowed: introduction -> rising -> crisis -> resolution -> transformed
  - Disallowed: skipping stages, going backwards
  - Raise ValueError on invalid transition

### S4.5 Phase S4 Tests

- [x] Test world state persistence: run graph, verify DB state, run again, verify continuity
- [x] Test frontier escalation trigger on scene_writer retry
- [x] Test budget degradation: scene count reduced when budget exceeded
- [x] Test arc_stage transition validation (valid and invalid)
- [~] Test full 3-episode sequence with Ollama: world state compounds correctly (requires live Ollama; covered by 2-episode mock test)

---

## Open Decisions

| Decision | Default | Notes |
|----------|---------|-------|
| Audience profile: shared pool or per-world? | Per-world (embedded JSON) | Simpler; can extract to separate table later |
| Scene writing: all-at-once or per-scene calls? | All-at-once (one agent call) | Consistent with platform pattern; per-scene possible as v1 optimization |
| Episode versioning: semver or episode-number? | Episode-number (E001) | Semver adds complexity for creative content with no clear benefit |
| TTS integration point | Narration script text output only (v0) | TTS adapter can be added later as a post-publish hook |
| Tension curve scoring | Deferred to v1 | Merged into audience compliance; standalone TensionCurveAgent if needed later |
| Theme auditing | Folded into QA gate rules | Standalone ThemeAuditorAgent if rules become complex |

# PRD: Story World Persistent Memory System

## 0. Document Purpose

Specify a fourth product loop for the AI Swarm Platform: a **persistent, audience-aware story world engine** that maintains long-term canon across episodes, adapts to audience profiles, and produces versioned narrative artifacts. This PRD is written to the same standard as the main `PRD.MD` — minimal ambiguity, implementable by a coding agent.

This module reuses the shared swarm infrastructure (orchestrator, agent runtime, data layer, snapshot/delta engine, QA gates, publisher, model routing, budgeting) and adds story-domain agents, data models, and a new graph.

---

## 1. Goals

### 1.1 Primary Goals

1. **Persistent world memory**: story canon (characters, places, rules, events) survives across sessions and episodes via the existing claim/entity/snapshot spine.
2. **Episodic generation**: produce structured, multi-scene episodes with act structure, tension curves, and character arcs — not one-shot stories.
3. **Audience adaptation**: formally constrain vocabulary, complexity, tone, pacing, and content to a declared audience profile.
4. **Internal continuity**: prevent contradictions in world rules, character traits, and timeline using the existing contradiction detection system.
5. **Compounding narrative state**: each episode updates the world state — new entities, resolved threads, character arc progression, timeline advancement — tracked via snapshots and deltas.

### 1.2 Secondary Goals

- Produce audio-ready narration scripts (text formatting only — no TTS in v0).
- Generate "previously on" recaps from delta reports.
- Support long-horizon story arcs (seasons, series) through thread tracking.

---

## 2. Non-Goals (v0)

- Full publishing platform or reader UI.
- Interactive branching narratives or reader-driven choices.
- Multi-author collaborative editing.
- Text-to-speech synthesis (v0 produces formatted scripts only).
- Cover art, music, or multimedia generation.
- Real-time feedback-driven story adaptation.

---

## 3. Scope and Relationship to Existing Platform

### 3.1 Scope Type

The story system uses `scope_type = "story"` and `scope_id = <world_id>`. Each graph run produces one episode for one world.

### 3.2 Reused Infrastructure

| Component | How it is reused |
|-----------|-----------------|
| Orchestrator | Executes the story graph — same `execute_graph()` |
| BaseAgent | All story agents inherit from BaseAgent with the same contract |
| Entity store | Characters, places, artifacts stored as entities with `type` field distinguishing them |
| Claim store | Canonical story facts stored as claims — `claim_type` extended with story-domain values |
| Snapshot + Delta | World state versioned after each episode; delta reports track what changed |
| QA Validator | Extended with story-domain gate rules |
| Publisher | Produces story artifacts (episode text, narration script, recap, manifest) |
| Budget system | Same per-node/per-run/per-scope enforcement |
| Model routing | Local model for scene drafting; frontier escalation for emotional nuance, thematic synthesis |

### 3.3 What Is New

- 6 new story-domain agents (premise, plot, scene_writer, canon_updater, audience_compliance, narration_formatter)
- 4 new DB tables (story_worlds, characters, narrative_threads, episodes)
- 1 new graph YAML (story_graph.yaml)
- 1 new CLI script (run_story.py)
- Story-domain QA gate rules
- Audience profile data structure (stored as JSON in story_worlds, not a separate table)

---

## 4. Data Model

### 4.1 story_worlds

Stores the persistent world configuration and metadata. One row per world.

```
story_worlds(
    world_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    genre           TEXT NOT NULL,           -- e.g. "fantasy", "sci-fi", "mystery"
    tone            TEXT NOT NULL,           -- e.g. "dark", "whimsical", "serious"
    setting_json    TEXT NOT NULL DEFAULT '{}',  -- physics rules, cultural rules, geography
    thematic_constraints_json TEXT NOT NULL DEFAULT '[]',  -- list of required/forbidden themes
    audience_profile_json     TEXT NOT NULL DEFAULT '{}',  -- embedded AudienceProfile
    current_episode_number    INTEGER NOT NULL DEFAULT 0,
    current_timeline_position TEXT NOT NULL DEFAULT 'start',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
```

**audience_profile_json schema:**
```json
{
    "age_range": "8-12",
    "vocabulary_level": "intermediate",
    "max_violence": "mild",
    "max_complexity": "moderate",
    "preferred_tone": "adventurous",
    "target_word_count": 3000,
    "target_scene_count": 5,
    "pacing": "fast"
}
```

### 4.2 characters

Characters are stored both as entities (in the shared entity store, for cross-referencing with claims/relationships) AND in this domain table for story-specific attributes the entity store cannot represent.

```
characters(
    character_id    TEXT PRIMARY KEY,        -- matches entity_id in entities table
    world_id        TEXT NOT NULL REFERENCES story_worlds(world_id),
    name            TEXT NOT NULL,
    role            TEXT NOT NULL,           -- "protagonist", "antagonist", "supporting", "minor"
    arc_stage       TEXT NOT NULL DEFAULT 'introduction',  -- "introduction", "rising", "crisis", "resolution", "transformed"
    alive           INTEGER NOT NULL DEFAULT 1,
    traits_json     TEXT NOT NULL DEFAULT '[]',   -- canonical personality traits
    goals_json      TEXT NOT NULL DEFAULT '[]',   -- current goals
    fears_json      TEXT NOT NULL DEFAULT '[]',
    beliefs_json    TEXT NOT NULL DEFAULT '[]',   -- internal beliefs that can change
    voice_notes     TEXT NOT NULL DEFAULT '',      -- prose style notes for this character's dialogue
    meta_json       TEXT NOT NULL DEFAULT '{}'
)
```

### 4.3 narrative_threads

Tracks open and resolved storylines across episodes.

```
narrative_threads(
    thread_id           TEXT PRIMARY KEY,
    world_id            TEXT NOT NULL REFERENCES story_worlds(world_id),
    title               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',  -- "open", "escalating", "climax", "resolved"
    introduced_in_episode INTEGER NOT NULL,
    resolved_in_episode   INTEGER,                      -- NULL if still open
    thematic_tag        TEXT NOT NULL DEFAULT '',
    related_character_ids_json TEXT NOT NULL DEFAULT '[]',
    escalation_points_json     TEXT NOT NULL DEFAULT '[]',  -- [{episode, description}]
    meta_json           TEXT NOT NULL DEFAULT '{}'
)
```

### 4.4 episodes

Tracks the generated episodes and their structural metadata.

```
episodes(
    episode_id      TEXT PRIMARY KEY,
    world_id        TEXT NOT NULL REFERENCES story_worlds(world_id),
    episode_number  INTEGER NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    act_structure_json TEXT NOT NULL DEFAULT '[]',  -- [{act, scenes: [...]}]
    scene_count     INTEGER NOT NULL DEFAULT 0,
    word_count      INTEGER NOT NULL DEFAULT 0,
    tension_curve_json TEXT NOT NULL DEFAULT '[]',  -- [float] per scene
    snapshot_id     TEXT,                            -- snapshot taken after this episode
    run_id          TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',   -- "draft", "revised", "final"
    created_at      TEXT NOT NULL,
    meta_json       TEXT NOT NULL DEFAULT '{}'
)
```

### 4.5 Mapping to Shared Spine

| Story Concept | Shared Structure | Notes |
|--------------|-----------------|-------|
| Character | Entity (`type = "character"`) + characters table | Entity for cross-referencing; domain table for arc/traits |
| Place | Entity (`type = "place"`) | Standard entity |
| Artifact/Object | Entity (`type = "artifact"`) | Standard entity |
| Canonical fact | Claim (`claim_type = "canon_fact"`) | "The kingdom fell in year 300" |
| World rule | Claim (`claim_type = "world_rule"`) | "Magic requires a spoken incantation" |
| Character trait | Claim (`claim_type = "character_trait"`) | "Aria is fearless" — can be disputed/superseded |
| Event | Claim (`claim_type = "event"`) | "The dragon attacked the village in episode 3" |
| Character relationship | Relationship | Standard relationship with confidence |
| World snapshot | Snapshot (`scope_type = "story"`) | Captures all claim/entity IDs for the world at a point in time |
| Episode delta | Delta | What changed in the world between episodes |

**Claim citations for story facts:** story claims use `doc_id = episode_id` and `segment_id = scene_id` to trace every canonical fact back to the scene that established it.

---

## 5. Story Graph

### 5.1 Graph Structure

The story graph generates one episode per run. The scene loop is flattened into the graph by having the `scene_writer` agent process all planned scenes in a single call (consistent with how `lesson_composer` handles all objectives and `question_generator` handles all questions in existing graphs).

```yaml
id: story_graph
entry: world_memory_load
nodes:
  world_memory_load:
    agent: story_memory_loader
    inputs: [world_id]
    outputs: [world_state, characters, active_threads, previous_snapshot, existing_claims, episode_number]
    next: premise

  premise:
    agent: premise_architect
    inputs: [world_state, characters, active_threads, audience_profile]
    outputs: [premise, episode_title, selected_threads]
    next: plot

  plot:
    agent: plot_architect
    inputs: [premise, characters, active_threads, selected_threads, audience_profile]
    outputs: [act_structure, scene_plans]
    next: scene_writing

  scene_writing:
    agent: scene_writer
    inputs: [act_structure, scene_plans, characters, world_state, audience_profile]
    outputs: [scenes, episode_text]
    next: canon_update

  canon_update:
    agent: canon_updater
    inputs: [scenes, characters, world_state, existing_claims]
    outputs: [new_claims, updated_characters, new_threads, resolved_threads, new_entities]
    next: contradiction_check

  contradiction_check:
    agent: contradiction
    inputs: [new_claims, existing_claims]
    outputs: [contradictions, updated_claim_ids]
    next: audience_check
    retry:
      max_attempts: 2
      backoff_seconds: 1.0

  audience_check:
    agent: audience_compliance
    inputs: [episode_text, audience_profile]
    outputs: [compliance_status, compliance_violations]
    next: qa_validation

  qa_validation:
    agent: qa_validator
    inputs: [new_claims, contradictions, compliance_status]
    outputs: [gate_status, violations]
    next: snapshot
    on_fail: scene_writing

  snapshot:
    agent: delta
    inputs: [claims, metrics]
    outputs: [snapshot_id, delta_id, delta_json, stability_score]
    next: narration

  narration:
    agent: narration_formatter
    inputs: [episode_text, characters, episode_title]
    outputs: [narration_script, recap]
    next: publish

  publish:
    agent: publisher
    inputs: [snapshot_id, delta_id]
    outputs: [publish_dir, manifest, artifacts]
    end: true
```

**11 nodes total.** 6 use new story agents, 3 reuse existing agents (contradiction, qa_validator via `on_fail`, delta, publisher), and 2 are shared deterministic agents.

### 5.2 Scene Writing Strategy

The `scene_writer` agent receives all scene plans and produces all scenes in a single call. This is consistent with the platform pattern (one agent call per graph node). The scene plans from `plot_architect` contain per-scene structure:

```json
[
    {
        "scene_id": "s1",
        "act": 1,
        "pov_character": "aria",
        "conflict": "Aria discovers the sealed door",
        "objective": "Introduce the mystery",
        "stakes": "If she ignores it, the curse spreads",
        "emotional_arc": "curiosity -> dread"
    }
]
```

If the total output exceeds the model's context window, the agent's POLICY should set `max_tokens` high enough, or the audience profile's `target_scene_count` should be kept reasonable (3-7 scenes for local models).

### 5.3 QA Failure and Revision

When `qa_validation` fails, the graph routes back to `scene_writing` via `on_fail`. The state still contains the `act_structure` and `scene_plans`, so the scene writer re-generates prose. The violations list is merged into state so the scene writer can see what went wrong (via `{violations}` in the prompt template).

---

## 6. Story-Specific Agents

### 6.1 StoryMemoryLoaderAgent

**Agent ID:** `story_memory_loader`
**LLM:** No — deterministic (overrides `run()`)
**Purpose:** Load world state from DB/previous snapshot into the run state dict.

Loads:
- World config from `story_worlds` table
- Characters from `characters` table
- Open threads from `narrative_threads` table (status != "resolved")
- Previous snapshot via `get_latest_snapshot()`
- Existing claims for this world
- Next episode number

This is analogous to `create_initial_state()` but story-specific. It overrides `run()` like `DeltaAgent` and `QAValidatorAgent`.

### 6.2 PremiseArchitectAgent

**Agent ID:** `premise_architect`
**LLM:** Yes
**Purpose:** Generate an episode premise aligned to world state, open threads, and audience profile.

Outputs:
- `premise`: 2-3 sentence episode concept
- `episode_title`: working title
- `selected_threads`: which open threads this episode will advance

Constraints:
- Must reference at least one open thread (or establish a new one if none exist)
- Must respect world rules (provided in state)
- Must fit audience complexity range

### 6.3 PlotArchitectAgent

**Agent ID:** `plot_architect`
**LLM:** Yes
**Purpose:** Generate structured episode outline — acts, scenes, conflicts, character roles. No prose.

Outputs:
- `act_structure`: list of acts, each containing scene references
- `scene_plans`: list of scene plan objects (see 5.2 above)

Constraints:
- Scene count must be within audience profile's `target_scene_count` range
- Each scene must have a POV character that exists in the characters list
- Thread escalation must be planned for each selected thread

### 6.4 SceneWriterAgent

**Agent ID:** `scene_writer`
**LLM:** Yes (likely frontier escalation for emotional nuance)
**Purpose:** Generate prose for all scenes based on scene plans.

Outputs:
- `scenes`: list of `{scene_id, text, word_count}` objects
- `episode_text`: concatenated full episode text

Constraints:
- Must follow the scene plan structure
- Must respect audience profile (vocabulary, violence, complexity)
- Must not introduce world facts not present in existing claims or scene plans
- Total word count should be within audience profile's `target_word_count` +/- 20%

### 6.5 CanonUpdaterAgent

**Agent ID:** `canon_updater`
**LLM:** Yes
**Purpose:** Extract canonical changes from the generated scenes and register them.

Outputs:
- `new_claims`: new canonical facts established in this episode (using `claim_type` values: `canon_fact`, `world_rule`, `character_trait`, `event`)
- `updated_characters`: character state changes (arc progression, belief changes, goal changes)
- `new_threads`: any new narrative threads introduced
- `resolved_threads`: threads that reached resolution in this episode
- `new_entities`: any new characters/places/artifacts introduced

Each new claim must cite `doc_id = episode_id` and `segment_id = scene_id`.

### 6.6 AudienceComplianceAgent

**Agent ID:** `audience_compliance`
**LLM:** Yes
**Purpose:** Validate that the episode text meets audience profile constraints.

Outputs:
- `compliance_status`: "PASS" or "FAIL"
- `compliance_violations`: list of `{rule, detail, scene_id}` objects

Checks:
- Vocabulary difficulty vs `vocabulary_level`
- Sentence complexity vs `max_complexity`
- Violence/mature content vs `max_violence`
- Word count vs `target_word_count`
- Pacing assessment vs `pacing` preference

### 6.7 NarrationFormatterAgent

**Agent ID:** `narration_formatter`
**LLM:** Yes
**Purpose:** Convert episode text into read-aloud optimized format.

Outputs:
- `narration_script`: episode text reformatted for voice synthesis (stage directions, pause markers, emphasis cues, character voice tags)
- `recap`: "Previously on..." summary generated from the delta report and previous episode state

This agent runs after snapshot so it can use the delta_json for the recap.

---

## 7. Story-Domain QA Gate Rules

The existing `QAValidatorAgent` is extended with story-domain rules (same pattern as cert/dossier/lab domain gates):

### 7.1 Canon Integrity
- Every new claim must cite an episode_id and scene_id
- No new claim may directly contradict an existing active claim unless the contradiction agent flagged it

### 7.2 Character Consistency
- Characters referenced in scenes must exist in the characters list
- Character arc_stage transitions must follow the allowed sequence: introduction -> rising -> crisis -> resolution -> transformed

### 7.3 Thread Tracking
- At least one open thread must be advanced per episode
- Resolved threads must have had at least one escalation point before resolution

### 7.4 Audience Compliance
- `compliance_status` must be "PASS" (from AudienceComplianceAgent output)
- Word count within audience profile target +/- 30%

### 7.5 Structural Integrity
- Episode must have at least 2 scenes
- Every scene must have a POV character

---

## 8. Publishing

### 8.1 Output Artifacts

Published to `publish/out/story/<world_id>/<version>/`:

| File | Description |
|------|-------------|
| `manifest.json` | Standard manifest (version, snapshot_id, delta_id, generated_at) |
| `artifacts.json` | Standard artifact listing (paths + hashes) |
| `episode.json` | Structured episode data (acts, scenes, metadata) |
| `episode.md` | Readable episode text in Markdown |
| `narration_script.txt` | Voice-synthesis-ready script with stage directions |
| `recap.md` | "Previously on..." summary |
| `delta_json.json` | Standard delta report |
| `world_state.json` | Current world snapshot (characters, threads, claims summary) |

### 8.2 Versioning

Episodes use episode-number versioning: `E<number>` (e.g., `E001`, `E002`).

Within an episode, revisions use a draft counter: `E001-d1`, `E001-d2`, `E001-final`.

Published (final) episodes use the simple `E<number>` form. This is simpler than the semver scheme in the draft PDR and avoids the complexity of tracking major/minor/patch for creative content where "structural rewrite" vs "scene modification" is subjective.

---

## 9. Budget and Routing

### 9.1 Default Routing

| Agent | Default Model | Escalation Trigger |
|-------|--------------|-------------------|
| story_memory_loader | none (deterministic) | — |
| premise_architect | local | — |
| plot_architect | local | — |
| scene_writer | local | audience compliance failure, low tension score on retry |
| canon_updater | local | — |
| audience_compliance | local | — |
| narration_formatter | local | — |
| contradiction | local | ambiguity high |
| qa_validator | none (deterministic) | — |
| delta | none (deterministic) | — |
| publisher | none (deterministic) | — |

### 9.2 Budget Defaults

| Cap | Default |
|-----|---------|
| Max tokens per scene | 4096 |
| Max tokens per episode (all agents combined) | 32768 |
| Max frontier calls per episode | 2 |
| Degradation at | 80% of episode budget |
| Degradation behavior | Reduce scene count, simplify prose, skip narration formatting |

---

## 10. CLI Interface

```bash
# Generate an episode for a world
python -m scripts.run_story --world_id <id> [--sources <seed_json>] [--db <path>] [--model-call ollama:qwen2.5:7b] [-v]

# First run: --sources provides the world config seed data
# Subsequent runs: world state loaded from DB by StoryMemoryLoaderAgent
```

The `--sources` seed JSON for a new world:

```json
{
    "world": {
        "world_id": "enchanted-forest",
        "name": "The Enchanted Forest",
        "genre": "fantasy",
        "tone": "whimsical",
        "setting": {
            "physics_rules": ["Magic exists but costs energy", "Animals can talk"],
            "cultural_rules": ["Three kingdoms in uneasy alliance"],
            "geography": "Dense forest with a central lake"
        },
        "thematic_constraints": ["friendship", "courage", "consequences of choices"],
        "audience_profile": {
            "age_range": "8-12",
            "vocabulary_level": "intermediate",
            "max_violence": "mild",
            "max_complexity": "moderate",
            "preferred_tone": "adventurous",
            "target_word_count": 3000,
            "target_scene_count": 5,
            "pacing": "fast"
        }
    },
    "characters": [
        {
            "character_id": "aria",
            "name": "Aria",
            "role": "protagonist",
            "traits": ["curious", "brave", "impulsive"],
            "goals": ["Find the source of the forest's fading magic"],
            "fears": ["Being alone", "Letting others down"]
        }
    ]
}
```

---

## 11. Persistence Strategy

### 11.1 After Each Episode Run

1. **Canon update**: new claims written to claim store with `scope_type = "story"`, `scope_id = <world_id>`
2. **Character update**: character arc_stage, beliefs, goals updated in characters table
3. **Thread update**: new threads inserted, resolved threads marked, escalation points appended
4. **Episode record**: episode row inserted in episodes table
5. **World state update**: `current_episode_number` incremented, `current_timeline_position` advanced
6. **Snapshot**: standard snapshot captures all claim/entity IDs for the world
7. **Delta**: standard delta report shows what changed vs previous snapshot

### 11.2 Delta Report Contents (Story-Specific)

The standard delta_json (added/removed/changed claims) naturally captures:
- New canonical facts introduced
- Character trait changes (old trait claim superseded, new one active)
- New entities introduced
- Thread state changes (via claims tracking thread status)

The narration_formatter uses this delta to generate the "previously on" recap.

---

## 12. Testing Strategy

### 12.1 Unit Tests

- Story-domain agents: parse/validate for each new agent
- Audience compliance checks with sample text at various complexity levels
- Canon updater claim extraction from scene text
- Story-domain QA gate rules (each pass and fail case)

### 12.2 Integration Test

- Run story graph end-to-end with mock model responses
- Fixture: 1 world, 2 characters, 1 open thread, 3-scene episode
- Verify: episode produced, claims extracted, snapshot created, artifacts published
- Verify: second run picks up world state from first run's snapshot

### 12.3 Multi-Episode Continuity Test

- Run 2 consecutive episodes for the same world
- Verify: second episode references entities/claims from first
- Verify: delta report correctly shows what changed between episodes
- Verify: character arc progression is tracked

---

## 13. Future Extensions

- Interactive branching narratives (reader choices affect thread selection)
- Adaptive audience tuning based on engagement metrics
- Multi-world crossovers (shared entity resolution across worlds)
- Serialized subscription pipeline (scheduled episode generation)
- TTS integration (pass narration_script to voice synthesis API)
- Cover art generation (image model integration)
- Music scoring integration (mood-tagged audio selection)

---

## 14. Relationship to Draft PDR

This PRD resolves the following issues in the original `docs/persistent_memory_story_system.md`:

| Issue | Resolution |
|-------|-----------|
| Scene loop undefined in graph format | Flattened: scene_writer processes all scenes in one call, consistent with platform pattern |
| WorldMemoryLoaderAgent described as LLM agent | Made deterministic (overrides `run()`), loads from DB |
| CanonUpdaterAgent "uses ClaimExtractorAgent internally" | Standalone agent — agents don't call other agents in this platform |
| TensionCurveAgent + ThemeAuditorAgent as separate agents | Merged into QA gate rules and audience_compliance agent to reduce agent count |
| ScenePlannerAgent as separate agent | Merged into PlotArchitectAgent which produces scene plans directly |
| NarrationFormatterAgent not in graph flow | Placed after snapshot, before publish |
| No concrete DB schema | Full table definitions provided |
| Audience profile as separate table | Embedded JSON in story_worlds (one profile per world, not a shared pool) |
| Episode versioning as full semver | Simplified to episode-number versioning (E001, E002) |
| No scope_type defined | `scope_type = "story"`, `scope_id = <world_id>` |
| Claim citations for fiction | `doc_id = episode_id`, `segment_id = scene_id` |
| Budget caps unspecified | Concrete defaults provided |
| 10 story-specific agents | Reduced to 6 by merging overlapping responsibilities |

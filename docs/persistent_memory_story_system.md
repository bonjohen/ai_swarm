```markdown
# PDR.MD — Story World Persistent Memory System

## 0. Purpose

Design a **persistent, audience-aware story world engine** that:

- Maintains long-term canon (world, characters, events)
- Writes stories episodically or continuously
- Adapts to a specified audience profile
- Reads stories aloud (voice synthesis integration point)
- Preserves internal continuity across stories
- Evolves world state over time

This module reuses shared AI swarm infrastructure:
- Source ingestion patterns
- Claim + entity modeling
- Snapshot + delta engine
- QA validation gates
- Publishing system
- Model routing + budgeting
- Versioning + state evolution

This is not a one-shot story generator.
It is a **narrative simulation system with memory**.

---

# 1. System Goals

## 1.1 Functional Goals

1. Persist world memory across sessions.
2. Persist character arcs across multiple stories.
3. Track unresolved narrative threads.
4. Adapt story complexity and tone to an audience profile.
5. Prevent internal contradictions.
6. Produce:
   - Episode drafts
   - Revised canonical episodes
   - “Previously on” summaries
   - Audio-ready narration scripts
7. Allow long-horizon story evolution (seasons/books).

---

## 2. Non-Goals (v0)

- Full publishing platform
- Interactive branching reader UI
- Multi-author collaborative editing
- Advanced multimedia integration

---

# 3. Core Concepts

## 3.1 Story World as Structured State

The story world is treated like a living dossier.

It has:
- Entities (characters, places, artifacts)
- Claims (canonical facts)
- Relationships
- Threads
- Snapshots
- Deltas

It uses the same structural spine as the Dossier System.

---

# 4. Data Model

## 4.1 StoryWorld

```

StoryWorld

* world_id
* genre
* tone
* physics_rules
* cultural_rules
* thematic_constraints
* audience_profile_id
* active_threads[]
* resolved_threads[]
* current_timeline_position
* snapshot_id

```

---

## 4.2 Character

```

Character

* character_id
* name
* role
* internal_beliefs[]
* goals[]
* fears[]
* arc_stage
* relationships[]
* voice_profile
* alive_status
* canonical_traits[]

```

---

## 4.3 NarrativeThread

```

NarrativeThread

* thread_id
* introduced_in_episode
* escalation_points[]
* resolution_status
* thematic_tag
* related_characters[]

```

---

## 4.4 Episode

```

Episode

* episode_id
* world_id
* act_structure
* scene_list[]
* tension_curve[]
* word_count
* draft_version
* final_version
* delta_from_previous

```

---

## 4.5 AudienceProfile

```

AudienceProfile

* profile_id
* age_range
* vocabulary_level
* tolerance_for_violence
* tolerance_for_complexity
* preferred_tone
* reading_duration_target
* moral_density_preference
* pacing_preference

```

---

# 5. Reused Shared Structures

The Story Engine reuses:

- Entity
- Claim
- Relationship
- Snapshot
- DeltaReport
- QA Validator
- Publisher
- Routing + Budget logic

Canonical story facts are stored as structured Claims.

---

# 6. Agents Used in Story Graph

Agents are modular and reusable.

---

## 6.1 Reused Agents (From Core Platform)

### 1. EntityResolverAgent
Used to:
- Prevent duplicate character entities
- Maintain world object identity

---

### 2. ClaimExtractorAgent
Used for:
- Extracting canonical facts from draft text
- Updating story canon

---

### 3. ContradictionAgent
Used for:
- Detecting world rule violations
- Detecting character trait inconsistencies
- Flagging arc contradictions

---

### 4. QAValidatorAgent
Used for:
- Ensuring story constraints are satisfied
- Ensuring audience compliance
- Ensuring unresolved threads tracked

---

### 5. DeltaAgent
Used for:
- Comparing episode versions
- Tracking world evolution
- Identifying character belief changes

---

### 6. PublisherAgent
Used for:
- Generating:
  - episode text
  - audio script
  - summary
  - “previously on” recap
- Version tagging

---

# 7. Story-Specific Agents

---

## 7.1 PremiseArchitectAgent

Purpose:
Generate premise aligned to world + audience profile.

Constraints:
- Must respect world constraints.
- Must align with theme.
- Must fit audience complexity range.

---

## 7.2 WorldMemoryLoaderAgent

Purpose:
Load:
- World state
- Character arcs
- Open threads
- Previous episode delta

Feeds structured state into generation agents.

---

## 7.3 PlotArchitectAgent

Purpose:
Generate structured episode outline.

Outputs:
- Act structure
- Scene objectives
- Character conflicts
- Thread escalation plan

No prose generation here.

---

## 7.4 ScenePlannerAgent

Purpose:
Generate scene skeleton:

- POV
- Conflict
- Objective
- Stakes
- Emotional delta

---

## 7.5 SceneWriterAgent

Purpose:
Generate scene prose.

Constraints:
- Must use structured plan.
- Must respect audience profile.
- Must not introduce canonical facts without registration.

---

## 7.6 CanonUpdaterAgent

Purpose:
After scene draft:
- Extract canonical facts.
- Register:
  - new entities
  - new threads
  - character belief changes
- Update Claim store.

Uses ClaimExtractorAgent internally.

---

## 7.7 TensionCurveAgent

Purpose:
Score:
- Emotional progression
- Escalation rate
- Act balance

---

## 7.8 ThemeAuditorAgent

Purpose:
Ensure episode aligns with thematic constraints.

---

## 7.9 AudienceComplianceAgent

Purpose:
Validate:
- Vocabulary difficulty
- Sentence complexity
- Content boundaries
- Pacing vs attention span

---

## 7.10 NarrationFormatterAgent

Purpose:
Convert episode into:
- Read-aloud optimized script
- Voice synthesis friendly format
- Chapter segmentation

---

# 8. Story Graph (High-Level)

```

load_world_memory
→ premise_architect
→ plot_architect
→ scene_loop
→ scene_planner
→ scene_writer
→ canon_update
→ contradiction_check
→ tension_score
→ audience_check
→ revise_if_needed
→ episode_snapshot
→ delta_generation
→ publish

```

---

# 9. Scene Loop Control Logic

For each planned scene:

1. Plan structure.
2. Write prose.
3. Extract canonical claims.
4. Detect contradictions.
5. Check audience constraints.
6. Score tension.
7. If fail:
   - revise
8. If pass:
   - append to episode
   - update world state

---

# 10. Persistence Strategy

StoryWorld state is versioned via Snapshot:

- After each episode:
  - create Snapshot(world_id)
  - store:
    - claim ids
    - character states
    - active threads
    - timeline index

Delta report describes:
- New threads
- Resolved threads
- Character arc movement
- Canonical rule changes

---

# 11. Versioning

Episodes use semantic versioning:

```

<world_id>_E<episode_number>_v<major>.<minor>.<patch>

```

Major:
- Structural rewrite

Minor:
- Scene modifications

Patch:
- Style edits

---

# 12. Budget and Routing

Default:
- Local model for scene drafting
- Frontier model for:
  - Complex thematic synthesis
  - Emotional nuance refinement

Escalation triggers:
- Audience compliance failure
- Tension scoring low
- Contradiction ambiguity high

Budget caps:
- Max tokens per scene
- Max tokens per episode
- Max frontier budget per episode

---

# 13. Output Artifacts

Publisher produces:

- episode_text.md
- episode_text.json
- narration_script.txt
- episode_manifest.json
- delta_report.json
- world_snapshot.json

---

# 14. Future Extensions

- Interactive branch graph
- Adaptive audience tuning
- Multi-world crossovers
- Serialized subscription pipeline
- Automated cover art generation
- Music scoring integration
- Dynamic story evolution based on listener feedback

---

# 15. Why This Architecture Works

Because:

- Story canon is treated like a technical dossier.
- Characters are entities.
- Facts are claims.
- Contradictions are managed.
- Deltas track evolution.
- Audience constraints are formalized.
- Versioning prevents drift.

It becomes:

A persistent narrative universe.
An episodic engine.
A story laboratory.
A memory-backed fiction factory.

---

If you’d like next, we can:

- Define the concrete graph YAML for this module
- Define minimal SQLite schema additions
- Or design the “audience adaptation algorithm” in detail
```

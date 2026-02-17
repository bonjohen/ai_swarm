-- ai_swarm core schema v0

-- ============================================================
-- Core tables
-- ============================================================

CREATE TABLE IF NOT EXISTS source_docs (
    doc_id      TEXT PRIMARY KEY,
    uri         TEXT NOT NULL,
    source_type TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    published_at TEXT,
    title       TEXT,
    content_hash TEXT,
    text_path   TEXT,
    license_flag TEXT DEFAULT 'open',
    meta_json   TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS source_segments (
    segment_id  TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL REFERENCES source_docs(doc_id),
    idx         INTEGER NOT NULL,
    text_path   TEXT,
    meta_json   TEXT DEFAULT '{}',
    UNIQUE(doc_id, idx)
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id   TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    names_json  TEXT NOT NULL DEFAULT '[]',
    props_json  TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id            TEXT PRIMARY KEY,
    scope_type          TEXT NOT NULL,
    scope_id            TEXT NOT NULL,
    statement           TEXT NOT NULL,
    claim_type          TEXT NOT NULL,
    entities_json       TEXT DEFAULT '[]',
    citations_json      TEXT DEFAULT '[]',
    evidence_strength   REAL,
    confidence          REAL,
    status              TEXT NOT NULL DEFAULT 'active',
    first_seen_at       TEXT NOT NULL,
    last_confirmed_at   TEXT,
    supersedes_json     TEXT DEFAULT '[]',
    meta_json           TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metrics (
    metric_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    unit            TEXT NOT NULL,
    scope_type      TEXT NOT NULL,
    scope_id        TEXT NOT NULL,
    dimensions_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metric_points (
    point_id    TEXT PRIMARY KEY,
    metric_id   TEXT NOT NULL REFERENCES metrics(metric_id),
    t           TEXT NOT NULL,
    value       REAL NOT NULL,
    doc_id      TEXT REFERENCES source_docs(doc_id),
    segment_id  TEXT,
    confidence  REAL,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS relationships (
    rel_id          TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    from_id         TEXT NOT NULL,
    to_id           TEXT NOT NULL,
    confidence      REAL,
    citations_json  TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id             TEXT PRIMARY KEY,
    scope_type              TEXT NOT NULL,
    scope_id                TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    hash                    TEXT NOT NULL,
    included_claim_ids_json TEXT DEFAULT '[]',
    included_metric_ids_json TEXT DEFAULT '[]',
    meta_json               TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS deltas (
    delta_id            TEXT PRIMARY KEY,
    scope_type          TEXT NOT NULL,
    scope_id            TEXT NOT NULL,
    from_snapshot_id    TEXT REFERENCES snapshots(snapshot_id),
    to_snapshot_id      TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    created_at          TEXT NOT NULL,
    delta_json          TEXT NOT NULL DEFAULT '{}',
    stability_score     REAL,
    summary             TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    scope_type  TEXT NOT NULL,
    scope_id    TEXT NOT NULL,
    graph_id    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    status      TEXT NOT NULL DEFAULT 'running',
    cost_json   TEXT DEFAULT '{}',
    meta_json   TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_events (
    event_id    TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    t           TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    status      TEXT NOT NULL,
    cost_json   TEXT DEFAULT '{}',
    payload_json TEXT DEFAULT '{}'
);

-- ============================================================
-- Certification domain tables
-- ============================================================

CREATE TABLE IF NOT EXISTS cert_objectives (
    objective_id TEXT PRIMARY KEY,
    cert_id      TEXT NOT NULL,
    code         TEXT NOT NULL,
    text         TEXT NOT NULL,
    weight       REAL NOT NULL DEFAULT 1.0,
    prereqs_json TEXT DEFAULT '[]',
    meta_json    TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cert_modules (
    module_id    TEXT PRIMARY KEY,
    objective_id TEXT NOT NULL REFERENCES cert_objectives(objective_id),
    version      TEXT NOT NULL,
    content_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cert_questions (
    question_id                TEXT PRIMARY KEY,
    objective_id               TEXT NOT NULL REFERENCES cert_objectives(objective_id),
    version                    TEXT NOT NULL,
    qtype                      TEXT NOT NULL,
    content_json               TEXT NOT NULL DEFAULT '{}',
    grounding_claim_ids_json   TEXT DEFAULT '[]'
);

-- ============================================================
-- Lab domain tables
-- ============================================================

CREATE TABLE IF NOT EXISTS lab_models (
    model_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    family      TEXT,
    params_b    REAL,
    context_len INTEGER,
    quant       TEXT,
    provider    TEXT,
    revision    TEXT,
    caps_json   TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS lab_hardware (
    hw_id       TEXT PRIMARY KEY,
    spec_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS lab_tasks (
    task_id          TEXT PRIMARY KEY,
    category         TEXT NOT NULL,
    prompt_template  TEXT NOT NULL,
    golden_json      TEXT DEFAULT '{}',
    rubric_json      TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS lab_runs (
    lab_run_id   TEXT PRIMARY KEY,
    suite_id     TEXT NOT NULL,
    model_id     TEXT NOT NULL REFERENCES lab_models(model_id),
    hw_id        TEXT NOT NULL REFERENCES lab_hardware(hw_id),
    t            TEXT NOT NULL,
    settings_json TEXT DEFAULT '{}',
    cost_json    TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS lab_results (
    result_id       TEXT PRIMARY KEY,
    lab_run_id      TEXT NOT NULL REFERENCES lab_runs(lab_run_id),
    task_id         TEXT NOT NULL REFERENCES lab_tasks(task_id),
    scores_json     TEXT DEFAULT '{}',
    fail_modes_json TEXT DEFAULT '[]',
    notes           TEXT
);

-- ============================================================
-- Learner telemetry tables
-- ============================================================

CREATE TABLE IF NOT EXISTS learner_events (
    event_id     TEXT PRIMARY KEY,
    cert_id      TEXT NOT NULL,
    learner_id   TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    objective_id TEXT,
    question_id  TEXT,
    score        REAL,
    t            TEXT NOT NULL,
    meta_json    TEXT DEFAULT '{}'
);

-- ============================================================
-- Story domain tables
-- ============================================================

CREATE TABLE IF NOT EXISTS story_worlds (
    world_id                  TEXT PRIMARY KEY,
    name                      TEXT NOT NULL,
    genre                     TEXT NOT NULL,
    tone                      TEXT NOT NULL,
    setting_json              TEXT NOT NULL DEFAULT '{}',
    thematic_constraints_json TEXT NOT NULL DEFAULT '[]',
    audience_profile_json     TEXT NOT NULL DEFAULT '{}',
    current_episode_number    INTEGER NOT NULL DEFAULT 0,
    current_timeline_position TEXT NOT NULL DEFAULT 'start',
    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS characters (
    character_id TEXT PRIMARY KEY,
    world_id     TEXT NOT NULL REFERENCES story_worlds(world_id),
    name         TEXT NOT NULL,
    role         TEXT NOT NULL,
    arc_stage    TEXT NOT NULL DEFAULT 'introduction',
    alive        INTEGER NOT NULL DEFAULT 1,
    traits_json  TEXT NOT NULL DEFAULT '[]',
    goals_json   TEXT NOT NULL DEFAULT '[]',
    fears_json   TEXT NOT NULL DEFAULT '[]',
    beliefs_json TEXT NOT NULL DEFAULT '[]',
    voice_notes  TEXT NOT NULL DEFAULT '',
    meta_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS narrative_threads (
    thread_id                  TEXT PRIMARY KEY,
    world_id                   TEXT NOT NULL REFERENCES story_worlds(world_id),
    title                      TEXT NOT NULL,
    status                     TEXT NOT NULL DEFAULT 'open',
    introduced_in_episode      INTEGER NOT NULL,
    resolved_in_episode        INTEGER,
    thematic_tag               TEXT NOT NULL DEFAULT '',
    related_character_ids_json TEXT NOT NULL DEFAULT '[]',
    escalation_points_json     TEXT NOT NULL DEFAULT '[]',
    meta_json                  TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS episodes (
    episode_id         TEXT PRIMARY KEY,
    world_id           TEXT NOT NULL REFERENCES story_worlds(world_id),
    episode_number     INTEGER NOT NULL,
    title              TEXT NOT NULL DEFAULT '',
    act_structure_json TEXT NOT NULL DEFAULT '[]',
    scene_count        INTEGER NOT NULL DEFAULT 0,
    word_count         INTEGER NOT NULL DEFAULT 0,
    tension_curve_json TEXT NOT NULL DEFAULT '[]',
    snapshot_id        TEXT,
    run_id             TEXT,
    status             TEXT NOT NULL DEFAULT 'draft',
    created_at         TEXT NOT NULL,
    meta_json          TEXT NOT NULL DEFAULT '{}'
);

-- ============================================================
-- Router telemetry tables
-- ============================================================

CREATE TABLE IF NOT EXISTS routing_decisions (
    decision_id     TEXT PRIMARY KEY,
    run_id          TEXT,
    node_id         TEXT,
    agent_id        TEXT,
    request_tier    INTEGER NOT NULL,
    chosen_tier     INTEGER NOT NULL,
    provider        TEXT,
    escalation_reason TEXT,
    confidence      REAL,
    complexity_score REAL,
    quality_score   REAL,
    latency_ms      REAL,
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    cost_usd        REAL,
    created_at      TEXT NOT NULL
);

-- ============================================================
-- Indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_claims_scope ON claims(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_metrics_scope ON metrics(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_metric_points_metric ON metric_points(metric_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_scope ON snapshots(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_deltas_scope ON deltas(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_runs_scope ON runs(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_source_segments_doc ON source_segments(doc_id);
CREATE INDEX IF NOT EXISTS idx_cert_objectives_cert ON cert_objectives(cert_id);
CREATE INDEX IF NOT EXISTS idx_cert_modules_obj ON cert_modules(objective_id);
CREATE INDEX IF NOT EXISTS idx_cert_questions_obj ON cert_questions(objective_id);
CREATE INDEX IF NOT EXISTS idx_lab_runs_suite ON lab_runs(suite_id);
CREATE INDEX IF NOT EXISTS idx_lab_results_run ON lab_results(lab_run_id);
CREATE INDEX IF NOT EXISTS idx_learner_events_cert ON learner_events(cert_id);
CREATE INDEX IF NOT EXISTS idx_learner_events_learner ON learner_events(cert_id, learner_id);
CREATE INDEX IF NOT EXISTS idx_characters_world ON characters(world_id);
CREATE INDEX IF NOT EXISTS idx_threads_world ON narrative_threads(world_id);
CREATE INDEX IF NOT EXISTS idx_threads_status ON narrative_threads(world_id, status);
CREATE INDEX IF NOT EXISTS idx_episodes_world ON episodes(world_id);
CREATE INDEX IF NOT EXISTS idx_episodes_number ON episodes(world_id, episode_number);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_run ON routing_decisions(run_id);

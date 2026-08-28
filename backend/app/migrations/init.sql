CREATE TABLE IF NOT EXISTS users (
    id             TEXT PRIMARY KEY,
    email          TEXT UNIQUE NOT NULL,
    name           TEXT,
    password_hash  TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
    id                   TEXT PRIMARY KEY,
    created_by           TEXT NOT NULL REFERENCES users(id),
    name                 TEXT NOT NULL,
    framework            TEXT DEFAULT 'generic',
    audit_period_start   DATE NOT NULL,
    audit_period_end     DATE NOT NULL,
    current_phase        INTEGER NOT NULL DEFAULT 1,
    phase_status         JSONB NOT NULL DEFAULT '{"1":"pending","2":"pending","3":"pending","4":"pending"}'::jsonb,
    status               TEXT NOT NULL DEFAULT 'active',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Raw uploaded RCM, never mutated (audit trail) — one row per uploaded file/version.
CREATE TABLE IF NOT EXISTS rcm_uploads (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(id),
    file_path      TEXT NOT NULL,
    original_name  TEXT,
    column_map     JSONB DEFAULT '{}'::jsonb,
    passthrough    JSONB DEFAULT '[]'::jsonb,
    row_count      INTEGER,
    uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One row per control, normalized from the active rcm_upload.
CREATE TABLE IF NOT EXISTS controls (
    id                   TEXT PRIMARY KEY,
    project_id           TEXT NOT NULL REFERENCES projects(id),
    rcm_upload_id        TEXT NOT NULL REFERENCES rcm_uploads(id),
    control_id           TEXT NOT NULL,
    control_description  TEXT,
    risk_description      TEXT,
    risk_level             TEXT,
    control_type           TEXT,
    control_nature         TEXT,
    control_frequency      TEXT,
    control_owner          TEXT,
    process                TEXT,
    raw_row                JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, control_id)
);

-- Non-destructive edit overlay, keyed by control business-key.
CREATE TABLE IF NOT EXISTS control_overlays (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id),
    control_id   TEXT NOT NULL,
    field        TEXT NOT NULL,
    new_value    TEXT,
    source       TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, control_id, field)
);

-- Evidence file metadata (files themselves on local disk under storage/uploads/<project_id>/evidence/).
CREATE TABLE IF NOT EXISTS evidence_files (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    control_id      TEXT NOT NULL,
    sample_id       TEXT,
    file_path       TEXT NOT NULL,
    original_name   TEXT,
    file_type       TEXT,
    file_size       BIGINT,
    detected_mode   TEXT,   -- 'multi_sample' | 'invalid_format' | 'no_evidence'
    evidence_date   DATE,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_evidence_files_control ON evidence_files (project_id, control_id);

-- SOP document(s) uploaded for Phase 3.
CREATE TABLE IF NOT EXISTS sop_uploads (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    file_path       TEXT NOT NULL,
    original_name   TEXT,
    extracted_text  TEXT,
    parsed_steps    JSONB DEFAULT '[]'::jsonb,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One row per (project, phase) — flexible JSONB result blob + human-approval gate.
CREATE TABLE IF NOT EXISTS phase_results (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    phase           INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    result          JSONB NOT NULL DEFAULT '{}'::jsonb,
    approved_by     TEXT REFERENCES users(id),
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, phase)
);

-- Per-control testing attributes (Phase 4).
CREATE TABLE IF NOT EXISTS control_attributes (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    control_id      TEXT NOT NULL,
    worksteps       JSONB NOT NULL DEFAULT '[]'::jsonb,
    attributes      JSONB NOT NULL DEFAULT '[]'::jsonb,
    sample_columns  JSONB NOT NULL DEFAULT '[]'::jsonb,
    quality_issues  JSONB DEFAULT '[]'::jsonb,
    status          TEXT NOT NULL DEFAULT 'pending',
    approved_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, control_id)
);

-- Per-control testing results (Phase 4).
CREATE TABLE IF NOT EXISTS control_test_results (
    id                    TEXT PRIMARY KEY,
    project_id            TEXT NOT NULL REFERENCES projects(id),
    control_id            TEXT NOT NULL,
    test_mode             TEXT NOT NULL,
    total_samples         INTEGER DEFAULT 0,
    passed_samples        INTEGER DEFAULT 0,
    failed_samples         INTEGER DEFAULT 0,
    deviation_rate         NUMERIC(5,4) DEFAULT 0,
    effectiveness_status   TEXT,
    deficiency_type        TEXT,
    overall_remarks         TEXT,
    sample_results          JSONB DEFAULT '[]'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, control_id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    role            TEXT NOT NULL,
    content         TEXT,
    tool_name       TEXT,
    tool_args       JSONB,
    tool_result     JSONB,
    phase_at_time   INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_project ON chat_messages (project_id, created_at ASC);

CREATE TABLE IF NOT EXISTS artifacts (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(id),
    phase          INTEGER,
    filename       TEXT NOT NULL,
    file_path      TEXT NOT NULL,
    artifact_type  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

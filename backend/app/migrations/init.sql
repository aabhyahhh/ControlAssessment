-- ─────────────────────────────────────────────────────────────────────────
--  Workflow redesign (Sept 2026) — schema for the 4-step flow:
--    1. RCM Intake (Control ID is the only required column)
--    2. Adequacy Assessment (SOPs + monthly workpapers, one folder per control)
--    3. Evidence Requirements & Intake (declared list validated vs generated list)
--    4. Gap Assessment (Excel: received vs expected, severity, no TOE workpaper)
--
--  This migration is applied on every startup. The DROP statements below
--  retire tables and shapes from the previous (risk-inference + TOE) design.
--  There is no production data to preserve; a fresh DB simply skips the DROPs.
-- ─────────────────────────────────────────────────────────────────────────

DROP TABLE IF EXISTS control_test_results;
DROP TABLE IF EXISTS control_attributes;
-- sop_uploads is replaced by adequacy_documents (many rows, per-control, workpapers).
DROP TABLE IF EXISTS sop_uploads;

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

-- One row per control, normalized from the active rcm_upload. Only control_id
-- is guaranteed non-null; every other field is optional and may be
-- reconciled from the policy/SOP in step 2.
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

-- Step 2 — SOPs and monthly workpapers. One folder per Control ID; a file
-- with control_id NULL is a project-wide SOP. doc_kind is 'sop' | 'workpaper'.
-- period_month is the calendar month a workpaper covers (NULL for SOPs or
-- when it could not be inferred). parsed_steps is only meaningful for SOPs.
CREATE TABLE IF NOT EXISTS adequacy_documents (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    control_id      TEXT,
    doc_kind        TEXT NOT NULL DEFAULT 'sop',
    period_month    DATE,
    file_path       TEXT NOT NULL,
    original_name   TEXT,
    file_type       TEXT,
    file_size       BIGINT,
    extracted_text  TEXT,
    parsed_steps    JSONB DEFAULT '[]'::jsonb,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_adequacy_documents_project ON adequacy_documents (project_id, control_id);

-- Step 3 — the evidence the user declares they hold, per control, entered
-- through a structured UI. Validated against the engine-generated
-- required-documents list and against what was actually uploaded.
CREATE TABLE IF NOT EXISTS declared_evidence (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id),
    control_id   TEXT NOT NULL,
    items        JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, control_id)
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

-- Step 2 — emails sent to a control owner asking them to justify a
-- reconciliation mismatch (RCM vs SOP/workpaper contradiction). One row per
-- SEND; a single send can cover several controls/fields at once (batch).
CREATE TABLE IF NOT EXISTS justification_emails (
    id               TEXT PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects(id),
    recipient_email  TEXT NOT NULL,
    subject          TEXT NOT NULL,
    body             TEXT NOT NULL,
    sent_by          TEXT NOT NULL REFERENCES users(id),
    sent_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    send_status      TEXT NOT NULL DEFAULT 'sent',
    error_message    TEXT
);
CREATE INDEX IF NOT EXISTS idx_justification_emails_project ON justification_emails (project_id);

-- One row per (email, control, field) mismatch the email addressed. The
-- owner's reply is captured here manually (no inbox integration) — text
-- and/or an uploaded attachment — then analyzed by the LLM against the
-- specific mismatch it responds to.
CREATE TABLE IF NOT EXISTS justification_email_items (
    id                         TEXT PRIMARY KEY,
    justification_email_id    TEXT NOT NULL REFERENCES justification_emails(id),
    project_id                 TEXT NOT NULL REFERENCES projects(id),
    control_id                 TEXT NOT NULL,
    field                      TEXT,
    mismatch_description       TEXT NOT NULL,
    response_text              TEXT,
    response_attachment_path   TEXT,
    response_attachment_name   TEXT,
    response_uploaded_at       TIMESTAMPTZ,
    response_uploaded_by       TEXT REFERENCES users(id),
    analysis_verdict           TEXT,
    analysis_reasoning         TEXT,
    analyzed_at                 TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_justification_items_project_control
    ON justification_email_items (project_id, control_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id             TEXT PRIMARY KEY,
    project_id     TEXT NOT NULL REFERENCES projects(id),
    phase          INTEGER,
    filename       TEXT NOT NULL,
    file_path      TEXT NOT NULL,
    artifact_type  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

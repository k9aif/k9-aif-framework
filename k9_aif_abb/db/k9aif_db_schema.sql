-- ==========================================================
-- Intake Submission
-- ==========================================================
CREATE TABLE k9aif.intake_submission (
    intake_id UUID PRIMARY KEY,
    status VARCHAR(50) DEFAULT 'draft',
    questionnaire_version VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    submitted_at TIMESTAMP,
    s3_uri TEXT
);

-- ==========================================================
-- Intake Sections
-- ==========================================================
CREATE TABLE k9aif.intake_section (
    section_id UUID PRIMARY KEY,
    intake_id UUID REFERENCES k9aif.intake_submission(intake_id),
    section_name VARCHAR(50),  -- business_vision, current_state, target_state
    section_label VARCHAR(100),
    content TEXT,
    is_mandatory BOOLEAN DEFAULT TRUE,
    is_completed BOOLEAN DEFAULT FALSE,
    display_order INT,
    updated_at TIMESTAMP
);

-- ==========================================================
-- Workflow Events
-- ==========================================================
CREATE TABLE k9aif.workflow_event (
    event_id UUID PRIMARY KEY,
    intake_id UUID,
    event_type VARCHAR(50),
    event_status VARCHAR(50),
    payload_json JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================================
-- Artifact Records
-- ==========================================================
CREATE TABLE k9aif.artifact_record (
    artifact_id UUID PRIMARY KEY,
    intake_id UUID,
    artifact_type VARCHAR(50),
    storage_uri TEXT,
    status VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
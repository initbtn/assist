-- =============================================================================
-- Migration: Security Knowledge Base Schema (CWE, CAPEC, CVE)
-- Purpose: Structured storage for vulnerability taxonomy and threat intelligence
-- =============================================================================

-- 1. CWE Records: Common Weakness Enumeration (Software Flaws)
CREATE TABLE IF NOT EXISTS cwe_records (
    cwe_id VARCHAR(32) PRIMARY KEY,                  -- e.g., 'CWE-79', 'CWE-89'
    name VARCHAR(255) NOT NULL,
    abstraction VARCHAR(32),                         -- 'Class', 'Base', 'Variant'
    structure VARCHAR(32),                           -- 'Simple', 'Composite'
    status VARCHAR(32),                              -- 'Stable', 'Draft'
    description TEXT NOT NULL,
    extended_description TEXT,
    likelihood_of_exploit VARCHAR(32),               -- 'High', 'Medium', 'Low'
    mitigations JSONB DEFAULT '[]'::jsonb,           -- Recommended secure coding guidelines
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. CAPEC Records: Common Attack Pattern Enumeration and Classification
CREATE TABLE IF NOT EXISTS capec_records (
    capec_id VARCHAR(32) PRIMARY KEY,                -- e.g., 'CAPEC-66', 'CAPEC-248'
    name VARCHAR(255) NOT NULL,
    abstraction VARCHAR(32),                         -- 'Meta', 'Standard', 'Detailed'
    status VARCHAR(32),                              -- 'Stable', 'Draft'
    summary TEXT NOT NULL,
    prerequisites TEXT,
    severity VARCHAR(32),                            -- 'Very High', 'High', 'Medium', 'Low'
    likelihood_of_attack VARCHAR(32),                -- 'High', 'Medium', 'Low'
    related_cwe_ids TEXT[] DEFAULT '{}',             -- Mapped CWE IDs for cross-layer join
    attack_steps JSONB DEFAULT '[]'::jsonb,          -- Execution step-by-step
    mitigations JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. CVE Records: Common Vulnerabilities and Exposures
CREATE TABLE IF NOT EXISTS cve_records (
    cve_id VARCHAR(32) PRIMARY KEY,                  -- e.g., 'CVE-2026-12345'
    published_at TIMESTAMPTZ NOT NULL,
    last_modified_at TIMESTAMPTZ NOT NULL,
    severity VARCHAR(16) NOT NULL,                   -- 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    cvss_score NUMERIC(3, 1),                        -- e.g., 9.8
    cwe_ids TEXT[] DEFAULT '{}',                     -- Associated CWE IDs
    affected_packages JSONB DEFAULT '[]'::jsonb,     -- Affected package names & version ranges
    summary_en TEXT NOT NULL,
    summary_ko TEXT,                                 -- sLM synthesized Korean summary
    action_guide_ko TEXT,                            -- Concrete remediation recommendation
    source_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indices for rapid querying and RAG joining
CREATE INDEX IF NOT EXISTS idx_cwe_name ON cwe_records (name);
CREATE INDEX IF NOT EXISTS idx_capec_cwe_ids ON capec_records USING GIN (related_cwe_ids);
CREATE INDEX IF NOT EXISTS idx_cve_severity ON cve_records (severity);
CREATE INDEX IF NOT EXISTS idx_cve_published_at ON cve_records (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_cve_cwe_ids ON cve_records USING GIN (cwe_ids);
CREATE INDEX IF NOT EXISTS idx_cve_packages ON cve_records USING GIN (affected_packages);

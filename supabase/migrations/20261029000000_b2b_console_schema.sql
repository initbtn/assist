-- B2B Cloud Console Schema for assist platform
-- ADR 0001 & ADR 0002 compliance

CREATE TABLE IF NOT EXISTS apps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    app_id UUID NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    refresh_token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_key_hash ON api_tokens(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_tokens_refresh_hash ON api_tokens(refresh_token_hash);
CREATE INDEX IF NOT EXISTS idx_api_tokens_app_id ON api_tokens(app_id);

CREATE TABLE IF NOT EXISTS bot_configs (
    app_id UUID PRIMARY KEY REFERENCES apps(id) ON DELETE CASCADE,
    allowed_chat_ids TEXT[] DEFAULT '{}',
    enable_colab_gpu BOOLEAN DEFAULT TRUE,
    rate_limit_rpm INTEGER DEFAULT 60,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS provider_account (
    provider_account_id text PRIMARY KEY,
    provider_name text NOT NULL,
    credential_name text NOT NULL,
    list_url text NOT NULL,
    chat_base_url text NOT NULL,
    auth_scheme text NOT NULL,
    discovery_style text NOT NULL,
    task_filter text NOT NULL,
    enabled_flag boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider_name, credential_name)
);

CREATE TABLE IF NOT EXISTS provider_model (
    provider_model_id text PRIMARY KEY,
    provider_account_id text NOT NULL
        REFERENCES provider_account(provider_account_id) ON DELETE CASCADE,
    model_name text NOT NULL,
    chat_base_url text NOT NULL,
    auth_scheme text NOT NULL,
    prompt_price_per_1k numeric(20, 8),
    completion_price_per_1k numeric(20, 8),
    currency_code text NOT NULL,
    serving_eligible_flag boolean NOT NULL DEFAULT false,
    enabled_flag boolean NOT NULL DEFAULT true,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    UNIQUE (provider_account_id, model_name)
);

CREATE TABLE IF NOT EXISTS model_serving_tag (
    provider_model_id text NOT NULL
        REFERENCES provider_model(provider_model_id) ON DELETE CASCADE,
    tag_name text NOT NULL,
    PRIMARY KEY (provider_model_id, tag_name)
);

CREATE TABLE IF NOT EXISTS catalog_refresh_run (
    catalog_refresh_run_id text PRIMARY KEY,
    provider_account_id text NOT NULL
        REFERENCES provider_account(provider_account_id) ON DELETE CASCADE,
    refresh_status text NOT NULL,
    observed_model_count integer NOT NULL DEFAULT 0,
    eligible_model_count integer NOT NULL DEFAULT 0,
    error_code text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS provider_model_account_idx
    ON provider_model (provider_account_id, enabled_flag, serving_eligible_flag);
CREATE INDEX IF NOT EXISTS catalog_refresh_account_idx
    ON catalog_refresh_run (provider_account_id, finished_at DESC);

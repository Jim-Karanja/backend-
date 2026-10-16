-- Complaints Hub: PostgreSQL schema (prototype). Mirrors hub.models.Complaint and the run records.
CREATE TABLE IF NOT EXISTS demo_seeds (
    name TEXT PRIMARY KEY,
    seeded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS complaints (
    id              BIGSERIAL PRIMARY KEY,
    platform        TEXT        NOT NULL CHECK (platform IN ('facebook','instagram','x','linkedin','tiktok')),
    external_id     TEXT        NOT NULL,
    parent_post_id  TEXT,
    post_url        TEXT        NOT NULL,             -- permalink for "Reply Now"
    author_hash     TEXT        NOT NULL,             -- salted pseudonym, never the raw platform id
    text            TEXT        NOT NULL,
    lang            TEXT,
    created_at      TIMESTAMPTZ NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL,
    raw             JSONB       NOT NULL DEFAULT '{}',
    -- filled later by the MCP/AI layer and the dashboard
    category        TEXT,
    urgency         SMALLINT CHECK (urgency BETWEEN 1 AND 5),
    draft_reply     TEXT,
    status          TEXT        NOT NULL DEFAULT 'new',
    first_response_at TIMESTAMPTZ,
    UNIQUE (platform, external_id)                    -- makes every collection run idempotent
);
CREATE INDEX IF NOT EXISTS complaints_queue_idx ON complaints (status, urgency DESC, created_at);
ALTER TABLE complaints ADD COLUMN IF NOT EXISTS ai_reason TEXT;
ALTER TABLE complaints ADD COLUMN IF NOT EXISTS ai_model TEXT;
ALTER TABLE complaints ADD COLUMN IF NOT EXISTS ai_classified_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS collection_runs (
    id           BIGSERIAL PRIMARY KEY,
    platform     TEXT        NOT NULL,
    resource     TEXT        NOT NULL,
    params       JSONB       NOT NULL DEFAULT '{}',
    started_at   TIMESTAMPTZ NOT NULL,
    finished_at  TIMESTAMPTZ,
    fetched      INTEGER     NOT NULL DEFAULT 0,
    inserted     INTEGER     NOT NULL DEFAULT 0,
    pages        INTEGER     NOT NULL DEFAULT 0,
    stop_reason  TEXT,
    next_cursor  TEXT,
    complete     BOOLEAN     NOT NULL DEFAULT FALSE   -- false = "there may be complaints we did not see"
);

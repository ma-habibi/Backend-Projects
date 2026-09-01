-- Auto-executed once by the postgres:17 image on first container start
-- against an empty data directory (mounted at /docker-entrypoint-initdb.d/).
-- If the schema changes later, this file will NOT re-run against an
-- existing volume — dropping the volume or a migration tool is required.

CREATE TABLE IF NOT EXISTS appdb.users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(64) UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS appdb.images (
    id              VARCHAR(64) PRIMARY KEY,       -- matches the R2 object key
    user_id         INTEGER NOT NULL REFERENCES appdb.users(id) ON DELETE CASCADE,
    filename        VARCHAR(255) NOT NULL,
    format          VARCHAR(16) NOT NULL,
    width           INTEGER,
    height          INTEGER,
    size_bytes      BIGINT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_images_user_id ON appdb.images(user_id);
CREATE INDEX IF NOT EXISTS idx_images_created_at ON appdb.images(created_at);

-- Hackmash's database. The home server's sync job (backend/hackmash/sync.py)
-- writes it through the Worker's ingest API; the Worker reads it to serve the site.
-- Times are UTC text in one format (2026-11-11T12:00:00Z), so they compare as text.

-- One row per hackathon.
CREATE TABLE hackathons (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT NOT NULL,
  card TEXT NOT NULL,               -- JSON: the fields the board needs (no long text)
  detail TEXT NOT NULL,             -- JSON: every field, for the detail view
  hash TEXT NOT NULL,               -- of the row's content: the sync skips unchanged rows
  starts_at TEXT,
  ends_at TEXT,
  registration_deadline TEXT,
  submission_deadline TEXT,
  listed_until TEXT NOT NULL,       -- when it stops being current (ended or closed out)
  updated_at TEXT NOT NULL
);
CREATE INDEX hackathons_listed_until ON hackathons (listed_until);

-- Ids of the same event on other platforms, merged into one listing.
CREATE TABLE aliases (
  alias TEXT PRIMARY KEY,
  id TEXT NOT NULL
);
CREATE INDEX aliases_id ON aliases (id);

-- version, generated_at, taxonomy, fx, sources: JSON values written by each sync.
CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

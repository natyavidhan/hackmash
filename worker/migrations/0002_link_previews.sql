-- Link previews: what a shared link to a hackathon shows (written by the home server's sync).

-- The line under the preview, and the content hash of the poster that goes with it.
ALTER TABLE hackathons ADD COLUMN blurb TEXT;
ALTER TABLE hackathons ADD COLUMN og_hash TEXT;

-- One 1200×630 JPEG poster per hackathon, served at /og/<id>.jpg.
CREATE TABLE og_images (
  id TEXT PRIMARY KEY,
  hash TEXT NOT NULL,
  image BLOB NOT NULL,
  updated_at TEXT NOT NULL
);

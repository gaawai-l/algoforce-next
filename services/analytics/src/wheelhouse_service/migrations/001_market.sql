CREATE TABLE batches (
  batch_id TEXT PRIMARY KEY, stream_key TEXT NOT NULL, fetched_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX batches_stream_time ON batches(stream_key, fetched_at);
CREATE TABLE bar_revisions (
  revision_id TEXT PRIMARY KEY, stream_key TEXT NOT NULL, open_time TEXT NOT NULL,
  revision INTEGER NOT NULL, fetched_at TEXT NOT NULL, content_hash TEXT NOT NULL, payload TEXT NOT NULL,
  UNIQUE(stream_key, open_time, revision)
);
CREATE INDEX bars_as_known ON bar_revisions(stream_key, open_time, fetched_at);
CREATE TABLE observations (
  batch_id TEXT NOT NULL REFERENCES batches(batch_id), revision_id TEXT NOT NULL REFERENCES bar_revisions(revision_id),
  PRIMARY KEY(batch_id, revision_id)
);

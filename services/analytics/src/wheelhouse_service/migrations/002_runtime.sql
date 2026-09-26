CREATE TABLE snapshots (
  snapshot_id TEXT PRIMARY KEY, stream_key TEXT NOT NULL, created_at TEXT NOT NULL,
  input_hash TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX snapshots_stream_time ON snapshots(stream_key, created_at);
CREATE TABLE jobs (
  job_id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, request TEXT NOT NULL, stream_key TEXT NOT NULL,
  state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  next_attempt_at TEXT NOT NULL, lease_until TEXT, lease_token TEXT, checkpoint_batch_id TEXT,
  snapshot_id TEXT, error_code TEXT
);
CREATE INDEX jobs_due ON jobs(state, next_attempt_at, lease_until);
CREATE TABLE job_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES jobs(job_id), at TEXT NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE schedules (schedule_id TEXT PRIMARY KEY, stream_key TEXT NOT NULL UNIQUE, request TEXT NOT NULL, enabled INTEGER NOT NULL, next_due TEXT NOT NULL);

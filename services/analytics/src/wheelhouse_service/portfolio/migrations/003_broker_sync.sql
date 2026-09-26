CREATE TABLE broker_sync_jobs (
 id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, account TEXT NOT NULL,
 request TEXT NOT NULL, state TEXT NOT NULL, phase TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, next_due TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, lease_until TEXT, lease_token TEXT,
 capture TEXT, order_ids TEXT NOT NULL DEFAULT '[]', cursor INTEGER NOT NULL DEFAULT 0,
 missing_ids TEXT NOT NULL DEFAULT '[]', error TEXT
);
CREATE INDEX broker_sync_due ON broker_sync_jobs(state,next_due,lease_until);
CREATE TABLE broker_query_limits (
 account TEXT NOT NULL, operation TEXT NOT NULL, not_before TEXT NOT NULL,
 PRIMARY KEY(account,operation)
);

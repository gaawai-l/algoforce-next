-- A NULL value means BRK has no value for that position. It is never stored as zero.
CREATE TABLE IF NOT EXISTS series(
    series TEXT NOT NULL,
    idx TEXT NOT NULL,
    position INTEGER NOT NULL,
    value REAL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY(series, idx, position)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS series_meta(
    series TEXT NOT NULL,
    idx TEXT NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY(series, idx)
);
CREATE TABLE IF NOT EXISTS urpd(
    cohort TEXT NOT NULL,
    day TEXT NOT NULL,
    agg TEXT NOT NULL,
    close REAL NOT NULL,
    total_supply REAL NOT NULL,
    buckets_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY(cohort, day, agg)
);
CREATE TABLE IF NOT EXISTS derived(
    kind TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state(
    key TEXT PRIMARY KEY,
    value TEXT
);

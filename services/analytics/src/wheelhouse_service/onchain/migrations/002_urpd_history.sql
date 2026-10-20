-- The all-coins lin500 URPD history behind the cost-basis heatmap, one row per day.
-- supplies_json is the supply of every $500 bucket from $1,000 up, in BTC to 0.01, as a JSON array.
-- close and supplies_json are both NULL when BRK had no snapshot for the day when asked at fetched_at.
-- Only final snapshots are kept here, the forming ones stay in urpd.
CREATE TABLE IF NOT EXISTS urpd_history(
    day TEXT PRIMARY KEY,
    close REAL,
    supplies_json TEXT,
    fetched_at TEXT NOT NULL
)

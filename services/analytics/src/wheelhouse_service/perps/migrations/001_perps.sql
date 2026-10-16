-- Times are epoch seconds. A NULL value means the source has no usable value, never zero.
CREATE TABLE IF NOT EXISTS kline(
    venue TEXT NOT NULL,
    t INTEGER NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    taker_buy REAL,
    source TEXT NOT NULL,
    PRIMARY KEY(venue, t)
) WITHOUT ROWID;
-- `t` follows Binance openInterestHist's stamps: archive rows are stored at create_time + 300.
CREATE TABLE IF NOT EXISTS oi(
    venue TEXT NOT NULL,
    t INTEGER NOT NULL,
    oi REAL,
    source TEXT NOT NULL,
    PRIMARY KEY(venue, t)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS trades_10m(
    venue TEXT NOT NULL,
    t INTEGER NOT NULL,
    buy REAL NOT NULL,
    sell REAL NOT NULL,
    PRIMARY KEY(venue, t)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS trade_ids(
    venue TEXT NOT NULL,
    id TEXT NOT NULL,
    ts REAL NOT NULL,
    PRIMARY KEY(venue, id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS trade_ids_ts ON trade_ids(ts);
-- One row per event per connection: deduplicated by key when deriving.
CREATE TABLE IF NOT EXISTS liquidations(
    id INTEGER PRIMARY KEY,
    venue TEXT NOT NULL,
    conn INTEGER NOT NULL,
    event_ts REAL NOT NULL,
    raw_json TEXT NOT NULL,
    key TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS liquidations_venue_ts ON liquidations(venue, event_ts);
-- One row per connection: covered from start to end, the last proof of life.
CREATE TABLE IF NOT EXISTS coverage(
    id INTEGER PRIMARY KEY,
    stream TEXT NOT NULL,
    conn INTEGER NOT NULL,
    start REAL NOT NULL,
    end REAL NOT NULL,
    open INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS coverage_stream_end ON coverage(stream, end);
CREATE TABLE IF NOT EXISTS derived(
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state(
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Days whose data.binance.vision metrics file was not found, so it is not asked for every round.
CREATE TABLE IF NOT EXISTS archive_absent(
    day TEXT PRIMARY KEY
);

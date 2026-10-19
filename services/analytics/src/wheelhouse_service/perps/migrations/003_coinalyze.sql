-- Closed Coinalyze intervals (P6). step is 300 (5min) or 14400 (4hour), t the interval start.
-- liq: a = longs and b = shorts liquidated. ohlcv: a = volume and b = taker buy. oi: a = open
-- and b = close interest. All in BTC.
-- filled = 1 marks a liquidation interval Coinalyze left out of a fetched range, stored as 0.
CREATE TABLE IF NOT EXISTS cz_series(
    venue TEXT NOT NULL,
    kind TEXT NOT NULL,
    step INTEGER NOT NULL,
    t INTEGER NOT NULL,
    a REAL NOT NULL,
    b REAL NOT NULL,
    filled INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(venue, kind, step, t)
) WITHOUT ROWID;
-- The direction check is stored in a new shape from P6 on: the old one would not parse.
DELETE FROM sync_state WHERE key = 'direction_check';

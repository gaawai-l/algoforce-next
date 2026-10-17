-- How each stored liquidation counts (spec §3.1), set at insert time by store.liquidation_fields
-- and kept beside raw_json, so a derive sums them in SQL instead of parsing every event.
-- longs: 1 when longs were liquidated, 0 for shorts. qty: BTC, NULL when the event must not count
-- (a Binance status X other than FILLED). price: Bybit `p` for the size-unit check, NULL for
-- Binance. A field that cannot be read is NULL. The rows stored before this migration are mapped
-- here from raw_json the same way.
ALTER TABLE liquidations ADD COLUMN longs INTEGER;
ALTER TABLE liquidations ADD COLUMN qty REAL;
ALTER TABLE liquidations ADD COLUMN price REAL;
UPDATE liquidations SET
    longs = CASE json_extract(raw_json, '$.S') WHEN 'SELL' THEN 1 WHEN 'BUY' THEN 0 END,
    qty = CASE WHEN json_extract(raw_json, '$.X') = 'FILLED'
        THEN CAST(json_extract(raw_json, '$.z') AS REAL) END
WHERE venue = 'binance';
UPDATE liquidations SET
    longs = CASE json_extract(raw_json, '$.S') WHEN 'Buy' THEN 1 WHEN 'Sell' THEN 0 END,
    qty = CAST(json_extract(raw_json, '$.v') AS REAL),
    price = CASE WHEN json_extract(raw_json, '$.p') GLOB '*[0-9]*'
        AND json_extract(raw_json, '$.p') NOT GLOB '*[^0-9.eE+-]*'
        AND abs(CAST(json_extract(raw_json, '$.p') AS REAL)) < 9e999
        THEN CAST(json_extract(raw_json, '$.p') AS REAL) END
WHERE venue = 'bybit';

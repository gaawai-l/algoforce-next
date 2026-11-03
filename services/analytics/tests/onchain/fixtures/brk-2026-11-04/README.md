# BRK fixtures, 2026-11-04

Public data from https://bitview.space (no auth, no account data), captured 2026-11-04 01:20–01:25
SGT (2026-11-03 17:20Z) for the BRK upgrade check in `research/source-diff-2026-11-04.md`. Do not
edit the JSON by hand.

- BRK `/version` at capture time: `"66f66db"` (the 0.12.2 of the 2026-10-16 fixtures is gone).
- Series responses no longer carry `stamp`.
- URPD responses carry `height`, `hash` and `weight`, the total as `supply`, and the buckets as
  columns: `buckets.price` (the bucket floor), `buckets.supply`, `buckets.realized_cap`,
  `buckets.unrealized_pnl`.

| File | Request |
| --- | --- |
| `bulk_hour1_156376.json` | `/api/series/bulk?series=price_close,age_under_1h_supply_in_loss&index=hour1&start=156376&end=156378` |
| `urpd_all_lin500_2026-11-02.json` | `/api/urpd/all/2026-11-02?agg=lin500` |
| `urpd_age_under_1h_lin500_2026-11-02.json` | `/api/urpd/age_under_1h/2026-11-02?agg=lin500` |

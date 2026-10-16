# BRK fixtures, 2026-10-16

Public data from the Bitcoin Research Kit instance at https://bitview.space (no auth, no account
data). Replayed by `../../onchain_fixture.py`; do not edit the JSON by hand.

- BRK `/version` at capture time: `0.12.2`.
- Every `day1_*.json` is a single-series response: `start` 1461 (2013-01-01, position 0 is
  2009-01-01), `end` 6498 (exclusive, so the last point is position 6497 = 2026-10-16), 5,037
  points, no `null`s. Positions are shared by `day1` and `hour1`.
- `version` is per series, so values are not comparable between files.
- The last point of each series is the still-forming 2026-10-16 day; the files were captured at
  different times (see `stamp`), so those last points are not one consistent snapshot.
- Every `hour1_*.json` is a single-series response: `start` 153338 (2026-07-06T02:00Z), `end`
  155938 (exclusive, so the last point is position 155937 = 2026-10-16T09:00Z), 2,600 points, the
  last one not `null`. All 11 files have the same 11 `null`s: hours in which no block was mined
  (positions 153394, 153501, 153521, 153572, 153695, 153715, 154243, 154384, 154682, 155630 and
  155634). The captures were taken at 10:01Z to 10:02Z, so the 09:00 hour was already closed.
- Responses keep fields the client models ignore: `type` on series, `weight` on URPD.

| File | Request | `version` | `stamp` | Origin |
| --- | --- | --- | --- | --- |
| `day1_price_close.json` | `price_close` day1 from 2013-01-01 | 89 | 2026-10-16T10:02:04Z | sample copy |
| `day1_true_market_mean.json` | `true_market_mean` | 53 | 2026-10-16T10:02:05Z | sample copy |
| `day1_sth_realized_price.json` | `sth_realized_price` | 4126600471 | 2026-10-16T10:02:06Z | sample copy |
| `day1_utxos_1d_to_1w_old_realized_price.json` | `utxos_1d_to_1w_old_realized_price` | 4217680034 | 2026-10-16T10:02:08Z | sample copy |
| `day1_realized_price.json` | `realized_price` | 4126600474 | 2026-10-16T10:19:46Z | sample copy |
| `day1_lth_realized_price.json` | `lth_realized_price` | 4126600472 | 2026-10-16T13:39:43Z | fetched 2026-10-16 |
| `hour1_price_close.json` | `price_close` hour1, 2,600 points | 89 | 2026-10-16T10:01:53Z | sample copy |
| `hour1_sth_realized_profit_cumulative.json` | `sth_realized_profit_cumulative` | 4091783938 | 2026-10-16T10:01:54Z | sample copy |
| `hour1_sth_realized_loss_cumulative.json` | `sth_realized_loss_cumulative` | 4091783938 | 2026-10-16T10:01:55Z | sample copy |
| `hour1_lth_realized_profit_cumulative.json` | `lth_realized_profit_cumulative` | 2560347083 | 2026-10-16T10:01:56Z | sample copy |
| `hour1_lth_realized_loss_cumulative.json` | `lth_realized_loss_cumulative` | 2560347083 | 2026-10-16T10:01:58Z | sample copy |
| `hour1_utxos_under_1h_old_realized_profit_cumulative.json` | `utxos_under_1h_old_realized_profit_cumulative` | 4217679986 | 2026-10-16T10:01:58Z | sample copy |
| `hour1_utxos_under_1h_old_realized_loss_cumulative.json` | `utxos_under_1h_old_realized_loss_cumulative` | 4217679986 | 2026-10-16T10:01:59Z | sample copy |
| `hour1_sth_supply_in_loss.json` | `sth_supply_in_loss` | 4099232015 | 2026-10-16T10:02:00Z | sample copy |
| `hour1_sth_supply_in_profit.json` | `sth_supply_in_profit` | 4099232015 | 2026-10-16T10:02:01Z | sample copy |
| `hour1_utxos_under_1h_old_supply_in_loss.json` | `utxos_under_1h_old_supply_in_loss` | 1011942293 | 2026-10-16T10:02:02Z | sample copy |
| `hour1_utxos_under_1h_old_supply_in_profit.json` | `utxos_under_1h_old_supply_in_profit` | 1011942293 | 2026-10-16T10:02:03Z | sample copy |
| `urpd_all_lin500.json` | `/api/urpd/all/2026-10-16?agg=lin500` | n/a | n/a (no stamp; `date` 2026-10-16, `close` 82154.25) | fetched 2026-10-16T13:39:58Z |
| `urpd_{sth,lth}_lin500.json`, `urpd_{all,sth,lth}_lin{200,1000}.json` | `/api/urpd/{cohort}/2026-10-16?agg=lin{N}` | n/a | n/a (no stamp; `date` 2026-10-16, `close` 81217.6) | copy of `../brk-2026-10-16T1829Z/` (fetched 2026-10-16T18:29:37Z) |

## Origin

- Sample copies are byte-for-byte copies from the gitignored local research samples
  `.local/research-samples/alpha-dashboards-2026-10-16/` (captured 2026-10-16 10:01Z to 10:19Z):
  the first four from `onchain-seller/data/d_*.json`, `realized_price` from
  `onchain-pulse/data/d_realized_price.json`.
- The `hour1_*.json` files are byte-for-byte copies of `onchain-seller/data/h_<series>.json` in the
  same samples (captured 2026-10-16 10:01Z to 10:02Z; `meta.json` there says `fetched_at_utc`
  2026-10-16T10:01:52Z, 16 requests). `h_timestamp.json` is not copied: hour1 time is derived from
  the position. Each request asked for the last 2,600 points of one series, which BRK answered with
  the absolute `start`.
- `day1_lth_realized_price.json` was fetched on 2026-10-16 with
  `GET /api/series/bulk?series=lth_realized_price&index=day1&start=2013-01-01&end=2026-10-17`.
  The one-element array that endpoint returns was unwrapped to its single object (outer brackets
  removed, bytes otherwise unchanged) to match the sample copies.
- `urpd_all_lin500.json` was fetched on 2026-10-16 with `GET /api/urpd/all/2026-10-16?agg=lin500`,
  unchanged (252 buckets, `price_floor` 0 to 125,500 in steps of 500).
- The other 8 `urpd_*.json` are byte-for-byte copies of the same-named files in
  `../brk-2026-10-16T1829Z/`, so the sync can fetch all 9 snapshots of the day. They were captured
  at 18:29Z, not 13:39Z like `urpd_all_lin500.json` here, and do not match it (`close` 81217.6
  against 82154.25). Never assert cost-basis values on this directory: assert them only on
  `../brk-2026-10-16T1829Z/`.
- Version mismatch: none to report. The two fetched items have no earlier sample to compare
  with, and the fetched series has the same `start`/`end` as the samples.

## How the fake BRK replays them

`brk_transport()` in `../../onchain_fixture.py` answers `/api/series/bulk` from these files.

- A negative `start` is the last N points (as on the live API); the body's `start` is always the
  absolute position of its first row. The live API returns N points; a fixture holds only 2,600
  hour1 points, so a `start=-3000` replay returns all 2,600, with `start` 153338. A positive
  `start` or a date earlier than a file's own `start` is served from the file's `start` the same
  way.
- The weight cap uses the number of points asked for (about 16 weight each, 320,000 per request),
  not the fewer a fixture can return, so a bulk request of more than 6 hour1 series at
  `start=-3000` is rejected with `weight_exceeded`, as on the live API.
- `fail_index={"hour1"}` makes every series request for that index return 503.

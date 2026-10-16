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
- Responses keep fields the client models ignore: `type` on series, `weight` on URPD.

| File | Request | `version` | `stamp` | Origin |
| --- | --- | --- | --- | --- |
| `day1_price_close.json` | `price_close` day1 from 2013-01-01 | 89 | 2026-10-16T10:02:04Z | sample copy |
| `day1_true_market_mean.json` | `true_market_mean` | 53 | 2026-10-16T10:02:05Z | sample copy |
| `day1_sth_realized_price.json` | `sth_realized_price` | 4126600471 | 2026-10-16T10:02:06Z | sample copy |
| `day1_utxos_1d_to_1w_old_realized_price.json` | `utxos_1d_to_1w_old_realized_price` | 4217680034 | 2026-10-16T10:02:08Z | sample copy |
| `day1_realized_price.json` | `realized_price` | 4126600474 | 2026-10-16T10:19:46Z | sample copy |
| `day1_lth_realized_price.json` | `lth_realized_price` | 4126600472 | 2026-10-16T13:39:43Z | fetched 2026-10-16 |
| `urpd_all_lin500.json` | `/api/urpd/all/2026-10-16?agg=lin500` | n/a | n/a (no stamp; `date` 2026-10-16, `close` 82154.25) | fetched 2026-10-16T13:39:58Z |

## Origin

- Sample copies are byte-for-byte copies from the gitignored local research samples
  `.local/research-samples/alpha-dashboards-2026-10-16/` (captured 2026-10-16 10:01Z to 10:19Z):
  the first four from `onchain-seller/data/d_*.json`, `realized_price` from
  `onchain-pulse/data/d_realized_price.json`.
- `day1_lth_realized_price.json` was fetched on 2026-10-16 with
  `GET /api/series/bulk?series=lth_realized_price&index=day1&start=2013-01-01&end=2026-10-17`.
  The one-element array that endpoint returns was unwrapped to its single object (outer brackets
  removed, bytes otherwise unchanged) to match the sample copies.
- `urpd_all_lin500.json` was fetched on 2026-10-16 with `GET /api/urpd/all/2026-10-16?agg=lin500`,
  unchanged (252 buckets, `price_floor` 0 to 125,500 in steps of 500).
- Version mismatch: none to report. The two fetched items have no earlier sample to compare
  with, and the fetched series has the same `start`/`end` as the samples.

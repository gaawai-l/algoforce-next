# BRK all-coins URPD history fixtures (Chart 8)

Public data from the Bitcoin Research Kit instance at https://bitview.space (no auth, no account
data): six all-coins lin500 URPD snapshots for the cost-basis history of state-report Chart 8.
Read by `history_urpd()` in `../../onchain_fixture.py`; do not edit the JSON by hand.

- Every file is one unchanged response of `GET /api/urpd/all/<date>?agg=lin500`, saved as
  `urpd_all_lin500_<date>.json`. Each response has `cohort` `all`, `weight` `raw`, `aggregation`
  `lin500`, its own `close` and `buckets` with `price_floor` from 0 in steps of $500.
- Responses keep `weight`, which the client models ignore. The history reads only `close` and
  each bucket's `price_floor` and `supply`.
- The six files hold 151,163 bytes together.

| File | Request | Captured | BRK `/version` | Buckets | `close` | Origin |
| --- | --- | --- | --- | --- | --- | --- |
| `urpd_all_lin500_2022-10-20.json` | `/api/urpd/all/2022-10-20?agg=lin500` | 2026-10-19 05:00-05:30Z | version not recorded (SR-8-A:3) | 137, $0-$68,000 (135 from $1,000) | 19044.07 | stage-A copy |
| `urpd_all_lin500_2025-10-20.json` | `/api/urpd/all/2025-10-20?agg=lin500` | 2026-10-19 05:00-05:30Z | version not recorded (SR-8-A:3) | 252, $0-$125,500 (250 from $1,000) | 110893.6 | stage-A copy |
| `urpd_all_lin500_2026-07-21.json` | `/api/urpd/all/2026-07-21?agg=lin500` | 2026-10-20T09:27:50Z | `0.12.2` | 252, $0-$125,500 (250 from $1,000) | 66154.98 | fetched |
| `urpd_all_lin500_2026-09-19.json` | `/api/urpd/all/2026-09-19?agg=lin500` | 2026-10-20T09:27:51Z | `0.12.2` | 252, $0-$125,500 (250 from $1,000) | 81270.08 | fetched |
| `urpd_all_lin500_2026-10-12.json` | `/api/urpd/all/2026-10-12?agg=lin500` | 2026-10-20T09:27:51Z | `0.12.2` | 252, $0-$125,500 (250 from $1,000) | 81963.83 | fetched |
| `urpd_all_lin500_2026-10-18.json` | `/api/urpd/all/2026-10-18?agg=lin500` | 2026-10-20T09:27:52Z | `0.12.2` | 252, $0-$125,500 (250 from $1,000) | 81844.61 | fetched |

## Origin

- The two stage-A copies are byte-for-byte copies (checked with `cmp`) from the gitignored local
  research samples `.local/research-samples/alpha-dashboards-2026-10-16/`:
  `verification-2026-10-19/sr8/u_2022-10-20.json` and `verification-2026-10-19/sr8/u_2025-10-20.json`.
  Stage A (`verification-2026-10-19/verify/SR-8-A.md` line 3) fetched them on 2026-10-19 between
  05:00 and 05:30Z. It asked BRK for `/version` in that session but did not write the answer down,
  so their version is not recorded.
- The four fetched files are the finalised days of the stage-A table (SR-8-A §2.1, lines 92-95),
  which the local store had pruned by then. They were fetched on 2026-10-20 one after the other,
  right after `GET /version`, which answered `"0.12.2"` at 09:27:45Z (five requests in total). Each
  body was saved unchanged into an empty scratch directory, then copied here (`cmp`-identical):

  ```sh
  curl -sf -A curl/8.7.1 -o version.json https://bitview.space/version
  for d in 2026-07-21 2026-09-19 2026-10-12 2026-10-18; do
    curl -sf -A curl/8.7.1 -o "urpd_all_lin500_$d.json" \
      "https://bitview.space/api/urpd/all/$d?agg=lin500"
  done
  ```

- BRK had not revised those four days since stage A: each file matches the stage-A table cell by
  cell (`close`, the sum over the $1,000 grid, the largest bucket at $84,000, and the $60k, $74k,
  $82k and $100k buckets), which `test_history_row_matches_stage_a_cell_by_cell` in
  `../../test_onchain_costbasis_history.py` asserts.

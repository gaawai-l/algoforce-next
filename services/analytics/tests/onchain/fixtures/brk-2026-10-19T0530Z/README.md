# BRK sell-side golden sample, 2026-10-19 05:30Z

Public data from the Bitcoin Research Kit instance at https://bitview.space (no auth, no account
data). Read by `../../test_onchain_sellside.py`; do not edit the JSON by hand.

## How it was captured

During the 2026-10-19 chart verification (`docs/features/btc-onchain-perp/CHART-VERIFICATION.md`,
SR-1B), the original state-report page was open in a logged-in browser. Its global `DATA` was read
at 05:30Z and, 8 seconds later, the 25 hour1 series below were fetched in one bulk round
(`fetched_at` 2026-10-19T05:30:50.922345Z, positions 155006-156006, the last being the 05:00 UTC
hour, still forming). The last 96 rows of the page's `DATA` (25 keys each) matched a re-computation
from this fetch cell for cell, so the page used exactly these values.

| File | Content |
| --- | --- |
| `hour1_{series}.json` | The bulk response for each series, verbatim except that the `name` field each block carried was moved into the file name |
| `expected_sell_side.json` | The page's `DATA` for every kept row, re-computed from the files above by the independent port `recompute_c1b.py` (kept with the verification artifacts in `.local/research-samples/alpha-dashboards-2026-10-16/verification-2026-10-19/verify/sr1b/`) |

`expected_sell_side.json` is in the page's storage units: P&L in whole $100, USD volume in whole
$1000 (both rounded half up), BTC volume in 0.1 BTC (`toFixed(1)`), price to 0.1. Keys follow the
page: `LP`, `LL`, `SP`, `SL` are realized profit and loss of long- and short-term holders; a `b`
prefix is the spent volume in BTC, `u` in USD; an `x1` or `x24` suffix is the short-term leg
without the coins held under 1h or under 24h. `xgap` is 0: no excluded cohort had a gap.

## Series

`price_close`, `{sth,lth}_realized_{profit,loss}_cumulative`,
`{sth,lth}_transfer_volume_in_{profit,loss}_cumulative[_usd]`, and for both
`utxos_under_1h_old` and `utxos_1h_to_1d_old`: `_realized_{profit,loss}_cumulative` and
`_transfer_volume_in_{profit,loss}_cumulative[_usd]`.

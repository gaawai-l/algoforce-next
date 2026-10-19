# BRK age-cohort golden sample, 2026-10-19 14:53Z

Public data from the Bitcoin Research Kit instance at https://bitview.space (no auth, no account
data). Read by `../../test_onchain_agecohorts.py`; do not edit the JSON by hand.

## How it was captured

On 2026-10-19 from 14:53:38Z to 14:53:41Z the 139 hour1 series below were fetched in four bulk
requests, `GET /api/series/bulk?series=<names>&index=hour1&start=-400`, each item saved unchanged
except that the `name` field was moved into the file name. Every series covers positions
155615-156014; the last one is the 14:00 UTC hour, still forming. Positions 155630 and 155634 are
hours without a block: `null` in every series.

| File | Content |
| --- | --- |
| `hour1_{series}.json` | The bulk response for each series |
| `expected_age_cohorts.json` | The original state-report page's global `AGEPL` for these files |

`expected_age_cohorts.json` was produced by running the page's own loader code on the files above:
`raw/script_3_app.js` lines 33-47 (the cohorts and the twelve bands) and 219-247 (the chart 2
loader) of the saved page, copied verbatim into a Node harness that only replaces the network
fetch with these files (`sr2_loader_harness.js`, kept with the verification artifacts in
`.local/research-samples/alpha-dashboards-2026-10-16/verification-2026-10-19/verify/`).

It is in the page's storage units: `P`/`L` are realized profit and loss in whole $100, `uP`/`uL`
the spent volume in profit and at a loss in whole $1000 (both rounded half up), `bP`/`bL` the same
in BTC to 0.1 (`toFixed(1)`), each an array of the twelve bands of `groups`, youngest first. `PX`
is the price to 0.1; `t0` the first kept hour in Unix seconds and `H` each kept hour's offset from
it in hours. Of the 399 hours with an hour before them, 395 are kept: each blockless hour drops
itself and the hour after it.

## Series

`price_close` and, for each of the 23 UTXO age cohorts from `utxos_under_1h_old` to
`utxos_over_15y_old`: `_realized_{profit,loss}_cumulative` and
`_transfer_volume_in_{profit,loss}_cumulative[_usd]`.

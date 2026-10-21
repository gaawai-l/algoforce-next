# State-report Chart 8 acceptance readings, 2026-10-21 01:13Z

The original state-report page and this service's `GET /onchain/cost-basis-history?span=365`,
read within one minute of each other, once the history backfill had filled all 1,461 days. Public
on-chain aggregates only, no account data. Read by `test_sr8_acceptance_readings` in
`../../test_onchain_costbasis_history.py`; do not edit the files by hand.

Both sides leave out the forming last column (2026-10-21, today's snapshot), so every setting reads
the same closed days: 30D is 2026-09-22 to 10-20, 90D is 07-24 to 10-20, 365D is 2025-10-22 to
2026-10-20. Contrast is the default 75–95.

| Item | Value |
| --- | --- |
| Original page | `https://alphabtc-regime.vercel.app/onchain/state-report`, loaded 2026-10-21 ~01:13:10Z, read 01:14:08Z; its provenance line: "Data 2026-10-21 00:00 UTC" |
| Service | the controller's verification instance (port 8797), service code of `afe860a` (no service code changed up to main `534ad16`), `WHEELHOUSE_RULES=v1`; read 01:13:41Z, `computed_at` 01:12:52Z, right after the round that filled the last 15 days |
| BRK | `https://bitview.space/version`: `0.12.2`, on both sides |

| File | Content | How it was made |
| --- | --- | --- |
| `local-span365.json.gz` | The service's `?span=365` body, gzip of the raw bytes (838,512 B unzipped), `latest_day` 2026-10-21, no missing day | Fetched with `urllib` from `http://127.0.0.1:8797/api/wheelhouse/v1/onchain/cost-basis-history?span=365`; `?span=30` and `?span=90`, fetched in the same second, were checked to be its last 30 and 90 columns |
| `reference-output.json` | `cbh_reference.reference()` for each setting, on the last 30, 90 or 365 columns without the forming one | Written by the same script from the body above; the test recomputes it |
| `original-readings.json` | The original's reading of each setting without the forming column: first and last day, rows `r0`–`r1`, `n` cells, `floor`, `cap`, `top`; as shown with the forming column (`shown_with_forming`); and the $60k, $74k, $82k and $100k cells and close of four closed days | A console snippet on the loaded page (below) |

The original's `occupiedRange`, `visibleSorted` and `shaper8` live inside its script's closure, so
the snippet copies them from `raw/script_2_app.js` lines 3961-4018 of the research directory
(`.local/research-samples/alpha-dashboards-2026-10-16/state-report/`, not in the repository). For
each setting it clicks the page's own Span and Range buttons (30D, 90D and 365D are subsets of the
loaded days and Range only redraws, so neither fetches anything; All was not clicked), runs the
copies on `window._c8.dates` without its last day, and reads the page's Contrast handles. As a check
of the copies, it also runs them on the page's own view with the forming day and compares the
result with the page's `window._c8` (`r0`, `r1`, `sh.floor`, `sh.cap`): equal in all six settings
(`self_check`). The original keeps its cells as Float32, the service to 2 decimals.

The result, original against service:

| Setting | Rows | Cells | Largest floor / cap difference |
| --- | --- | --- | --- |
| 30D | 0–249, equal | 7,250, equal | 0.0019 / 0.0100 BTC |
| 90D | 0–249, equal | 22,250, equal | 0.0059 / 0.0038 BTC |
| 365D | 0–249, equal | 91,000, equal | 0.0009 / 0.0056 BTC |
| 365D ±50% | 80–247, equal | 61,152, equal | 0.0034 / 0.0013 BTC |
| 365D ±25% | 122–206, equal | 30,940, equal | 0.0019 / 0.0019 BTC |
| 365D ±10% | 147–181, equal | 12,740, equal | 0.0059 / 0.0025 BTC |

The 16 probe cells differ by at most 0.0113 BTC, and the four closes are equal. The test allows
0.05 BTC for floor and cap and 0.035 BTC for a probe cell (PLAN-SR8 Task 7).

SHA-256:

- `local-span365.json.gz`: `21ba75381de6efb64690ddc61d361a28106865e88f3828b23a72e40fd48c5b73`
- `original-readings.json`: `44999e517ca2451b59bce1eb4227e6fc6d9040f8f1aa86dd704dfd30112ef206`
- `reference-output.json`: `0b4f4ab2a046319de583489f27f541e4e1d6f9f142a5f9d9533c19925a520820`

# BRK cost-basis golden sample, 2026-10-16 18:29Z

Public data from the Bitcoin Research Kit instance at https://bitview.space (no auth, no account
data), plus readings of the original state-report page taken on the same data. Read by
`../../test_onchain_costbasis.py`; do not edit the JSON by hand.

## How it was captured

The original site's session had expired, and the agent does not type its password. Instead:

1. The saved original `state-report.html` was opened from `127.0.0.1`. It requested its data live
   from bitview.space as usual.
2. The BRK data below was fetched once before the page loaded and once after it had rendered all
   three bucket widths. Both fetches were byte-identical, so the page used exactly this data.

Fetch time (`meta.json` of the capture): `fetched_at_utc` 2026-10-16T18:29:37.786722Z, `date`
2026-10-16. The files are byte-for-byte copies from the gitignored
`.local/research-samples/p3-golden-20261016T1829Z/`, flattened into this one directory; only the
names in the table below changed.

| File | Content | Source in the sample |
| --- | --- | --- |
| `urpd_{all,sth,lth}_lin{200,500,1000}.json` | 9 URPD snapshots for 2026-10-16 (D), `close` 81217.6: responses of `/api/urpd/{cohort}/2026-10-16?agg=lin{N}` | `a/urpd_*.json` |
| `urpd_{cohort}_lin{N}_{date}.json` | 36 URPD snapshots for D-1, D-7, D-30 and D-90 (2026-10-15, 10-09, 09-16, 07-18); the page's grid is the union of floors over these and D | `past/*.json` |
| `urpd_{cohort}_lin{N}_{date}.json` (2026-10-14, 10-08, 09-15, 07-17) | 36 URPD snapshots for C-1, C-7, C-30 and C-90, the grid days of C = 2026-10-15 (see below); the page never read them | fetched later, below |
| `day1_{series}.json` | Last 3 day1 points (positions 6495-6497, the last being 2026-10-16) of `true_market_mean`, `sth_realized_price`, `realized_price`, `lth_realized_price` and `price_close` | `a/d_{series}.json` |
| `page.json` | Page readings for each bucket width (below) | `PAGE.json` |
| `expected-{200,500,1000}.json` | Full-precision results of the independent re-computation `state-report/tools/oracle_c7.py` | `expected-*.json` |

Last day1 values used as model lines: true_mean 77481.81, short_term 74475.07, average 53845.04,
long_term 49245.48. The median line is `median_cost` of `urpd_all_lin500.json`.

## `page.json`

Keyed by the bucket width actually drawn. Each entry holds Table 2 (`tbl2`), the nearest bands
(`near`: side, range, n, labels, distance from spot), the two panel subtitles (`subs`: total and
share in profit), the K and M marker labels (`labs`), the K positions (`peaks[].at`), and the M
mu, sigma and pi recovered from the rail's SVG geometry through the y-axis ticks (`dots`,
`beams`; float precision, `pi` from the dot radius `r = 2.5 + 3.5 * pi`).

- Table 2 prints $k with one decimal, so a whole multiple of $2,000 is exact.
- `"500"` is the boot view. Its bucket buttons mark $1000 and its meta line says "$1000 bands";
  both are a bucket-highlight bug of the original. The `"1000"` meta line says the same.

## `expected-*.json`

`oracle_c7.py` matches the page item by item (for example the STH M1 mu at $500: page
63384.48319993326, oracle 63384.483199933304). After review it gained two rules, BIC choice of k
when the KDE finds no peak and half-up rounding of two-decimal supplies; the expected files did
not change. Shapes differ from `BucketCostBasis`: peaks carry `at` instead of `price`, and bands
carry page labels (such as `STH M2 −σ` with U+2212, or `True mean`) instead of candidates.

## Snapshots of the closed day's grid (added for P5 O1)

Under rule O1 the cost basis is read from F, the latest closed day whose nine URPD snapshots are
final, rather than from D. At the capture time (2026-10-16 18:29Z) the closed day C is 2026-10-15,
which this sample already holds as D-1; its grid needs C-1, C-7, C-30 and C-90.

- Days: 2026-10-14, 2026-10-08, 2026-09-15, 2026-07-17; for each, all nine `{all,sth,lth}` x
  `lin{200,500,1000}` snapshots, 36 files.
- Source: the same public API, `https://bitview.space/api/urpd/{cohort}/{date}?agg=lin{N}`, the URL
  the service's `BrkClient.urpd` uses. Each file is the response body byte for byte, named like the
  other dated files.
- Fetched 2026-10-17T04:30:33Z-04:30:49Z UTC. Each day had closed well before then (a snapshot is
  final from 02:00 UTC on the next day), so these are final snapshots and read as they would have
  at the capture time. As a check, three snapshots already in this directory (`all lin500`
  2026-10-15, `sth lin200` 2026-10-09, `lth lin1000` 2026-07-18) were fetched again at that time
  and were byte-identical.
- The files for D and its own past days did not change. `golden_past` in the cost-basis tests
  reads only D-1, D-7, D-30 and D-90, as the page did.

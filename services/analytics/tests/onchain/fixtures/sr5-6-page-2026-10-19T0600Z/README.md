# State-report Charts 5 and 6 page sample, 2026-10-19 06:00Z

Readings of the original state-report page's global `SIZE` (Chart 5, Net Supply Change By Size
Cohorts) and `PNL` (Chart 6, Net Realized Profit & Loss By Size Cohorts), both at the hour
2026-10-19 06:00 UTC (hour1 position 156006, still forming when read). Public on-chain aggregates
only, no account data. Read by `../../sizes_fixture.py` for `../../test_onchain_sizes.py`; do not
edit the JSON by hand.

**These are the page's readings, not BRK values.** The hour1 rows the tests feed to
`size_cohorts()` are back-solved from these readings (below); they are not BRK's raw series.

`R` below is the gitignored research directory `.local/research-samples/alpha-dashboards-2026-10-16`
of the main checkout; `raw/script_3_app.js` is the original page's loader, saved as
`$R/state-report/raw/script_3_app.js`. The verification notes are
`$R/verification-2026-10-19/verify/SR-5.md` and `SR-6.md` (sections SR-5 and SR-6 of
`docs/features/btc-onchain-perp/CHART-VERIFICATION.md`).

| File | Content | Source, copied byte for byte |
| --- | --- | --- |
| `page_size.json` | `capturedAt` 2026-10-19T06:16:46.932Z, `sizeAsof` 06:00Z, and `SIZE`: the 12 bands of the page's `SIZE.bands`, smallest first, each `label`, `supply` (BTC, `+toFixed(2)`) and `d` (the change of each window) | `$R/verification-2026-10-19/verify/sr5/page-20261019T0616.json` |
| `page_pnl.json` | The page's `PNL.bands`, read at 06:21Z with `PNL.asof` 1792389600 (06:00Z), one row per band, smallest first: `[rcap, 1d p, 1d l, 7d p, 7d l, 30d p, 30d l, 90d p, 90d l]` in whole dollars (`Math.round`) | `$R/verification-2026-10-19/sr6/page-pnl-0600.json` |

SHA-256 of both copies, equal to their sources:

- `page_size.json`: `39e2194ecc25a04ad1950d08d2d29dc4cc8ebd22b1a72f89cb96e43f2708d522`
- `page_pnl.json`: `bed540af1c99da9086299c503c8e98f3ab750e1578a7b03374e2f13dde3f306a`

## How the readings were checked

Both readings were compared during the 2026-10-19 verification with independent re-computations
from BRK (bitview.space) at the same hour. The comparison was run again on 2026-10-20 from the
saved files, with the same result.

- **Chart 5** (SR-5.md line 23): `$R/verification-2026-10-19/verify/sr5/expected-20261019T0617.json`,
  computed by `sr5_expected.py` from a BRK fetch at 06:17:09Z whose last bar was 06:00. Every
  supply and change matches: max abs diff 0.00 BTC.
- **Chart 6** (SR-6.md line 22): `$R/verification-2026-10-19/sr6/oracle-0600.json`, computed by
  `chart6_oracle.py --asof 1792389600` from a BRK fetch with stamp 06:21:29Z. 106 of the 108
  values are equal; the other 2 differ by $1, from the rounding:
  - `under 1k sats`, 1d profit: page 89, oracle 88;
  - `10M sats–1 BTC`, 90d profit: page 2425253219, oracle 2425253218.

  The original rounds with JavaScript `Math.round` (`raw/script_3_app.js` line 335), which takes a
  half up; the oracle used Python `round()`, which takes it to even. The raw differences of those
  two cells are exactly 88.5 and 2425253218.5, confirmed by a second BRK fetch at 06:25Z
  (SR-6.md lines 43-45).

The window anchors are 2026-10-18 06:00 (1d), 10-12 06:00 (7d), 09-19 06:00 (30d) and 07-21 06:00
(90d); all four are closed hours with a block (SR-6.md lines 8-12 and 50).

## How the hour1 rows are back-solved

`sizes_fixture.golden_rows()` builds, for each of the 12 bands (the original's order,
`raw/script_3_app.js` lines 48-54) and each hour from SE − 2160h through SE = 06:00Z (2161 rows),
the four series the original reads (lines 125-131). Every value is `None` except at SE and the
four anchors SE − 24h, 168h, 720h and 2160h, so reading any other hour gives a missing cell.

- `<band>_supply`: at SE the page's `supply`; at SE − n the page's `supply` less its `d` for that
  window.
- `<band>_realized_profit_cumulative` and `<band>_realized_loss_cumulative`: at SE 1e12; at SE − n
  1e12 less the page's whole dollars for that window. The two half-dollar cells use the raw
  differences instead: 88.5 for the 1d profit of `addrs_under_1k_sats` and 2425253218.5 for the
  90d profit of `addrs_10m_sats_to_1btc`. Whole dollars and halves are exact floats around 1e12,
  so each difference comes back exactly.
- `<band>_realized_cap`: the page's `rcap` at SE, `None` elsewhere.

`size_cohorts()` on these rows must then give back every reading of both files, the two
half-dollar cells included.

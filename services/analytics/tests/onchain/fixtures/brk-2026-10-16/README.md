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
  last one not `null`. All hour1 files have the same 11 `null`s: hours in which no block was mined
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
| `day1_price_high.json`, `day1_price_low.json` | `price_high,price_low`, one request | 115 | 2026-10-19T05:13:46Z | slice of a sample (below) |
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
- `day1_price_high.json` and `day1_price_low.json` are positions 1461-6497 (`start` 1461, `end`
  6498) of the two elements of `verification-2026-10-19/verify/sr4/brk/hilo5600.json` in the same
  samples (element 0 `price_high`, element 1 `price_low`; `start` 901, captured
  2026-10-19T05:13:46Z), so they end on 2026-10-16 like the other day1 files, a day that had
  closed by then. Only `start`, `end` and `data` changed; the values equal the same positions of
  `../brk-2026-10-19T0512Z-costflow/day1_price_{high,low}.json`. Written from the repository
  root, with `R` the samples directory:

  ```sh
  python3 -I -c 'import json,sys
  h=json.load(open(sys.argv[1]))
  for e,name in zip(h,("price_high","price_low"),strict=True):
      s=e["start"]
      out={**e,"start":1461,"end":6498,"data":e["data"][1461-s:6498-s]}
      open(f"{sys.argv[2]}/day1_{name}.json","w").write(json.dumps(out,separators=(",",":")))' \
    "$R/verification-2026-10-19/verify/sr4/brk/hilo5600.json" services/analytics/tests/onchain/fixtures/brk-2026-10-16
  ```
- `urpd_all_lin500.json` was fetched on 2026-10-16 with `GET /api/urpd/all/2026-10-16?agg=lin500`,
  unchanged (252 buckets, `price_floor` 0 to 125,500 in steps of 500).
- The other 8 `urpd_*.json` are byte-for-byte copies of the same-named files in
  `../brk-2026-10-16T1829Z/`, so the sync can fetch all 9 snapshots of the day. They were captured
  at 18:29Z, not 13:39Z like `urpd_all_lin500.json` here, and do not match it (`close` 81217.6
  against 82154.25). Never assert cost-basis values on this directory: assert them only on
  `../brk-2026-10-16T1829Z/`.
- Version mismatch: none to report. The two fetched items have no earlier sample to compare
  with, and the fetched series has the same `start`/`end` as the samples.
- The 18 hour1 series the sell-side chart adds (`SELL_SIDE_SERIES` in `brk.py`: the transfer
  volumes of STH and LTH in BTC and USD, the under-1h cohort's transfer volumes, and every
  realized and transfer cumulative of `utxos_1h_to_1d_old`) were fetched on 2026-10-19 07:54Z with
  `GET /api/series/bulk?series=<6 names>&index=hour1&start=153338&end=155938`, three requests, each
  item saved unchanged. They cover the same positions as the other hour1 files and have the same
  11 `null`s. In the same minute `utxos_under_1h_old_realized_loss_cumulative` and
  `lth_realized_loss_cumulative` were fetched again over that window and matched the 10-16 files
  value for value and in `version`, so BRK had not revised that window since the capture.
- The 126 hour1 series only the age-cohort chart reads (`AGE_ONLY_SERIES` in `brk.py`: the six
  cumulatives of each UTXO age cohort from 1d-1w up, which the files above do not already have)
  were fetched on 2026-10-19 15:1xZ with
  `GET /api/series/bulk?series=<names>&index=hour1&start=155913&end=155938`, four requests, each
  item saved unchanged. They hold only the **last 25 hours** (positions 155913-155937, no `null`s),
  to keep the sample small: the sync derives the age cohorts from those hours alone. In the same
  minute `utxos_under_1h_old_realized_profit_cumulative`,
  `sth_transfer_volume_in_loss_cumulative_usd` and `price_close` were fetched again over that
  window and matched the files here value for value and in `version`.

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

## The 48 size-cohort series and `sizes-expected.json`

### The fixture files

- The 48 hour1 series the size-cohort charts read (`SIZE_SERIES` in `brk.py`: for each of the
  twelve `addrs_*` wallet-size bands, `_supply`, `_realized_profit_cumulative`,
  `_realized_loss_cumulative` and `_realized_cap`) were fetched on **2026-10-20 01:07:36Z to
  01:07:39Z** (BRK `/version` `0.12.2`) with
  `GET /api/series/bulk?series=<6 names>&index=hour1&start=153338&end=155938`, eight requests of 6
  names in `SIZE_SERIES` order (2,600 points × 6 × 16 = 249,600 weight each, under 320,000). Each
  item was saved unchanged in this directory's compact form, `hour1_<name>.json`, with the requests
  and the `json.dump` of this command. The script actually run differed only in writing into an
  empty scratch directory and fetching `price_close` (below) right after; the 48 files were then
  copied here, `cmp`-identical.

  ```sh
  python3 -I - <<'EOF'
  import json, subprocess
  bands = ["addrs_under_1k_sats", "addrs_1k_sats_to_10k_sats", "addrs_10k_sats_to_100k_sats",
           "addrs_100k_sats_to_1m_sats", "addrs_1m_sats_to_10m_sats", "addrs_10m_sats_to_1btc",
           "addrs_1btc_to_10btc", "addrs_10btc_to_100btc", "addrs_100btc_to_1k_btc",
           "addrs_1k_btc_to_10k_btc", "addrs_10k_btc_to_100k_btc", "addrs_over_100k_btc"]
  names = [b + s for b in bands for s in ("_supply", "_realized_profit_cumulative",
                                          "_realized_loss_cumulative", "_realized_cap")]
  for i in range(0, len(names), 6):
      part = names[i:i + 6]
      url = ("https://bitview.space/api/series/bulk?series=" + ",".join(part)
             + "&index=hour1&start=153338&end=155938")
      body = json.loads(subprocess.run(["curl", "-sf", "-A", "curl/8.7.1", url],
                                       check=True, capture_output=True).stdout)
      for name, item in zip(part, body, strict=True):
          with open(f"hour1_{name}.json", "w") as fh:
              json.dump(item, fh, separators=(",", ":"))
  EOF
  ```

- Checked file by file after the fetch: every one has `start` 153338, `end` 155938, 2,600 points,
  and its `null`s at exactly the 11 positions listed above (the hours without a block), no others.
  The 48 files hold 1,825,665 bytes together.
- In the same minute (request at 01:07:39Z, `stamp` 01:07:40Z) `price_close` was fetched again
  over the same window and matched `hour1_price_close.json` value for value, in `start`/`end` and
  in `version` (89), so BRK had not revised that window since the 10-16 capture. Unlike the other
  hour1 files, these 48 were not captured on 2026-10-16 itself: they are that window as BRK served
  it on 10-20.
- `version` is shared by `_supply` and `_realized_cap`, and by the two realized cumulatives, of
  one band; one `stamp` per band (`type` is `Bitcoin` for `_supply`, `Dollars` for the others):

  | Band | `version` of `_supply`, `_realized_cap` | `version` of `_realized_{profit,loss}_cumulative` | `stamp` |
  | --- | --- | --- | --- |
  | `addrs_under_1k_sats` | 414814695 | 152596763 | 2026-10-20T01:07:36Z |
  | `addrs_1k_sats_to_10k_sats` | 124746331 | 1259386547 | 2026-10-20T01:07:36Z |
  | `addrs_10k_sats_to_100k_sats` | 124746330 | 1259386548 | 2026-10-20T01:07:36Z |
  | `addrs_100k_sats_to_1m_sats` | 124746329 | 1259386549 | 2026-10-20T01:07:37Z |
  | `addrs_1m_sats_to_10m_sats` | 124746328 | 1259386542 | 2026-10-20T01:07:37Z |
  | `addrs_10m_sats_to_1btc` | 124746327 | 1259386543 | 2026-10-20T01:07:37Z |
  | `addrs_1btc_to_10btc` | 124746342 | 1259386544 | 2026-10-20T01:07:38Z |
  | `addrs_10btc_to_100btc` | 124746341 | 1259386545 | 2026-10-20T01:07:38Z |
  | `addrs_100btc_to_1k_btc` | 124746340 | 1259386538 | 2026-10-20T01:07:38Z |
  | `addrs_1k_btc_to_10k_btc` | 124746339 | 1259386539 | 2026-10-20T01:07:39Z |
  | `addrs_10k_btc_to_100k_btc` | 124746338 | 1259386540 | 2026-10-20T01:07:39Z |
  | `addrs_over_100k_btc` | 124746337 | 1259386541 | 2026-10-20T01:07:39Z |

### `sizes-expected.json`

- An **offline local recompute** from the 48 files above, run on 2026-10-20 with Python 3.12.7;
  it is not a reading of the original page. It does not import `wheelhouse_service` or read a
  store: it reads the JSON files and takes `data[position - start]`.
- The algorithm is that of the stage-A recompute scripts (paths under
  `.local/research-samples/alpha-dashboards-2026-10-16/verification-2026-10-19/`): the per-band
  `supply` and `d[w]` of `main()` in `verify/sr5/sr5_expected.py`, and the per-band `rcap` and
  `(p, l)` of `main()` in `sr6/chart6_oracle.py`. Each cell is `v[SE] - v[SE - n]` for
  n = 24/168/720/2160 hours, and `supply`, `realized_cap` are `v[SE]`.
- Two departures from those scripts. Rounding follows the original page, not Python `round()`:
  BTC as `toFixed(2)` (`Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP)`), dollars as
  `Math.round` (`math.floor(x + 0.5)`). A cell with either end `null` is `null`, never `null`
  as 0. The script also compares every cell with `round()`: **no cell differs** in either table.
- Top level: SE = 155937 (2026-10-16T09:00Z, the files' last position), anchors 155913, 155769,
  155217 and 153777. None of those 5 hours is one without a block, so the 168 cells (12 bands ×
  (2 + 4 windows × 3)) have no `null`, and `no_block` is `[]`.
- `cut_at_155802`: the same with SE = 155802 (2026-10-10T18:00Z), what a store cut after that
  position holds. Its 7d anchor is 155634 (2026-10-03T18:00Z), one of the hours without a block,
  so the 7d cells of every band (36) are `null` and `no_block` is `["7d"]`; the 1d, 30d and 90d
  anchors 155778, 155082 and 153642 all had a block.
- Written from the repository root with
  `python3 -I sizes_expected.py services/analytics/tests/onchain/fixtures/brk-2026-10-16 services/analytics/tests/onchain/fixtures/brk-2026-10-16/sizes-expected.json`,
  `sizes_expected.py` being exactly this; it printed only the two `SE …: N null cells` lines.
  Read only; never edit by hand.

```python
"""Offline recompute of the size-cohort table from the 48 hour1 fixture files.

Usage: python3 -I sizes_expected.py FIXTURE_DIR OUT_JSON
Reads FIXTURE_DIR/hour1_<band><suffix>.json only; imports nothing from the service.
"""

import json
import math
import sys
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

EPOCH = datetime(2009, 1, 1, tzinfo=UTC)  # hour1 position 0
BANDS = [
    "addrs_under_1k_sats", "addrs_1k_sats_to_10k_sats", "addrs_10k_sats_to_100k_sats",
    "addrs_100k_sats_to_1m_sats", "addrs_1m_sats_to_10m_sats", "addrs_10m_sats_to_1btc",
    "addrs_1btc_to_10btc", "addrs_10btc_to_100btc", "addrs_100btc_to_1k_btc",
    "addrs_1k_btc_to_10k_btc", "addrs_10k_btc_to_100k_btc", "addrs_over_100k_btc",
]
SUFFIXES = ["_supply", "_realized_profit_cumulative", "_realized_loss_cumulative", "_realized_cap"]
WIN = {"1d": 24, "7d": 168, "30d": 720, "90d": 2160}
SE = 155937  # 2026-10-16T09:00Z, the files' last position
CUT = 155802  # 2026-10-10T18:00Z: its 7d anchor 155634 is an hour without a block


def btc(x):  # +x.toFixed(2): the exact binary value, half up
    return None if x is None else float(Decimal(x).quantize(Decimal("0.01"), ROUND_HALF_UP))


def usd(x):  # Math.round
    return None if x is None else math.floor(x + 0.5)


def diff(a, b):
    return None if a is None or b is None else a - b


def table(series, se, btc_round, usd_round):
    def at(name, position):
        item = series[name]
        i = position - item["start"]
        return item["data"][i] if 0 <= i < len(item["data"]) else None

    bands = []
    for b in BANDS:
        windows = []
        for w, n in WIN.items():
            d = diff(at(b + "_supply", se), at(b + "_supply", se - n))
            p = diff(at(b + "_realized_profit_cumulative", se),
                     at(b + "_realized_profit_cumulative", se - n))
            l_ = diff(at(b + "_realized_loss_cumulative", se),
                      at(b + "_realized_loss_cumulative", se - n))
            windows.append({"window": w, "supply_change": btc_round(d),
                            "profit": usd_round(p), "loss": usd_round(l_)})
        bands.append({"band": b, "supply": btc_round(at(b + "_supply", se)),
                      "realized_cap": usd_round(at(b + "_realized_cap", se)),
                      "windows": windows})

    def blockless(position):
        return all(series[name]["start"] <= position < series[name]["end"]
                   and at(name, position) is None for name in series)

    return bands, [w for w, n in WIN.items() if blockless(se - n)]


def py_btc(x):  # the stage-A scripts' round(x, 2)
    return None if x is None else round(x, 2)


def py_usd(x):  # the stage-A scripts' round(x)
    return None if x is None else round(x)


def cells(bands):
    for band in bands:
        yield (band["band"], "supply"), band["supply"]
        yield (band["band"], "realized_cap"), band["realized_cap"]
        for w in band["windows"]:
            for key in ("supply_change", "profit", "loss"):
                yield (band["band"], w["window"], key), w[key]


def iso(position):
    return (EPOCH + timedelta(hours=position)).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    directory, out = Path(sys.argv[1]), Path(sys.argv[2])
    series = {b + s: json.loads((directory / f"hour1_{b}{s}.json").read_text())
              for b in BANDS for s in SUFFIXES}
    result = {"source": (
        "Offline recompute from the 48 hour1_addrs_*.json files in this directory (BRK, fetched "
        "2026-10-20T01:07Z, window 153338-155937), following the stage-A scripts "
        "verify/sr5/sr5_expected.py and sr6/chart6_oracle.py; rounding as the original page "
        "(toFixed(2) half up, Math.round). Not a reading of the original page.")}
    for key, se in (("", SE), ("cut_at_155802", CUT)):
        bands, no_block = table(series, se, btc, usd)
        section = {"last_at": iso(se), "no_block": no_block, "bands": bands}
        if key:
            result[key] = section
        else:
            result.update(section)
        theirs, _ = table(series, se, py_btc, py_usd)
        for (cell, mine), (_, other) in zip(cells(bands), cells(theirs), strict=True):
            if mine != other:
                print(f"rounding differs at SE {se} {cell}: page {mine!r}, round() {other!r}")
        nulls = sum(value is None for _, value in cells(bands))
        print(f"SE {se} ({iso(se)}): {nulls} null cells, no_block {no_block}")
    out.write_text(json.dumps(result, indent=1) + "\n")


if __name__ == "__main__":
    main()
```

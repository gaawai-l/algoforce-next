# BRK cost-basis flow sample, 2026-10-19 05:12Z

Public data from the Bitcoin Research Kit instance at https://bitview.space (no auth, no account
data), plus outputs of the independent re-computations made during the 2026-10-19 chart
verification (SR-3 and SR-4 in `docs/features/btc-onchain-perp/CHART-VERIFICATION.md`). Read by
`../../test_onchain_costflow.py`; do not edit the JSON by hand.

`R` below is the gitignored research directory `.local/research-samples/alpha-dashboards-2026-10-16`
of the main checkout. Every command was run from the repository root with that `R` set.

| File | Content |
| --- | --- |
| `urpd_{all,sth,lth}_{lin500,lin200}_{date}.json` | 30 URPD snapshots: D = 2026-10-19 and its window days 2026-10-18, 10-12, 09-19 and 07-21 |
| `day1_price_high.json`, `day1_price_low.json` | The last 5,600 day1 points of `price_high` and `price_low` |
| `expected_chart3.json` | Stage A: Chart 3's 23 states, re-computed on the same snapshots |
| `oracle-c4/c4_{1d,7d,30d,90d}_z0_2026-10-19.json` | Chart 4's rows at Zoom All for each window, from the oracle at 06:04:42Z |

## URPD snapshots

Source: the `urpd` table of `$R/verification-2026-10-19/verify/sr3/onchain-copy.sqlite`, a
read-only copy of the worker's database taken at 2026-10-19 05:13Z.

- The past days were fetched at 2026-10-19T04:52:31.696368Z, after each of them was final (from
  02:00 UTC on the next day).
- D was fetched at 2026-10-19T05:12:06.701470Z, while it was still forming.
- The copy holds 9 snapshots of D (all, sth and lth at lin1000, lin500 and lin200), every one at
  close 82347.76. Only the 6 at lin500 and lin200 are kept here, the same as for the past days.
- There are no age-cohort snapshots: the worker did not fetch them then.

Each file is `{"cohort","date","aggregation","close","total_supply","buckets"}` with `buckets`
= `json.loads(buckets_json)`. The `weight` field of the BRK response was dropped when the worker
stored it. The export command, verbatim (it wrote the 30 files):

```sh
python3 -I -c 'import json,sqlite3,sys; db=sqlite3.connect(f"file:{sys.argv[1]}?mode=ro",uri=True)
for c,d,a,cl,ts,bj in db.execute("select cohort,day,agg,close,total_supply,buckets_json from urpd where agg in (\"lin500\",\"lin200\")"):
    open(f"{sys.argv[2]}/urpd_{c}_{a}_{d}.json","w").write(json.dumps({"cohort":c,"date":d,"aggregation":a,"close":cl,"total_supply":ts,"buckets":json.loads(bj)},separators=(",",":")))' \
  "$R/verification-2026-10-19/verify/sr3/onchain-copy.sqlite" services/analytics/tests/onchain/fixtures/brk-2026-10-19T0512Z-costflow
```

## Daily high and low

Source: `$R/verification-2026-10-19/verify/sr4/brk/hilo5600.json`, a two-element day1 response
for `price_high,price_low`, requested in that order: element 0 is `price_high`, element 1
`price_low`. Element 0 is at least element 1 at every position, and neither has a `null`.

- `stamp` 2026-10-19T05:13:46Z, `version` 115.
- `start` 901 (2011-06-21), `end` 6501 (exclusive, so the last point is position 6500 =
  2026-10-19, still forming; position 0 is 2009-01-01).

Each element was serialized again on its own; no value changed. The command:

```sh
python3 -I -c 'import json,sys
h=json.load(open(sys.argv[1]))
for e,name in zip(h,("price_high","price_low"),strict=True):
    open(f"{sys.argv[2]}/day1_{name}.json","w").write(json.dumps(e,separators=(",",":")))' \
  "$R/verification-2026-10-19/verify/sr4/brk/hilo5600.json" services/analytics/tests/onchain/fixtures/brk-2026-10-19T0512Z-costflow
```

From 2013-01-01 on, these rows give the same age floor on every $500 row as the whole 5,600 days
do; the tests check both.

## Stage A and the Chart 4 oracle

Both are byte-for-byte copies:

```sh
F=services/analytics/tests/onchain/fixtures/brk-2026-10-19T0512Z-costflow
cp "$R/verification-2026-10-19/verify/sr3/store-result.json" "$F/expected_chart3.json"
mkdir -p "$F/oracle-c4"
for w in 1d 7d 30d 90d; do
  cp "$R/verification-2026-10-19/verify/sr4/out-B/c4_${w}_z0_2026-10-19.json" "$F/oracle-c4/"
done
```

- `expected_chart3.json` is the stage A reference implementation, run on the same database copy:
  23 states at full precision. It ports udiff and the segments from `chart3_recompute.py` and
  uses the KDE, peaks and GMM of `costbasis.py`. The same implementation, run on the 05:55
  snapshot, matched the original page line by line (396/396 lines, SR-3.md).
- `oracle-c4/` holds the Zoom All (`z0`) output of `oracle_c4.py`, which fetched its data at
  06:04:42Z (spot 82361.33), the same snapshot as the page's Chart 4 readings
  (`$R/verification-2026-10-19/verify/sr4/expected_B.json`). Each row carries `floor`, its age
  floor. Net buy and net sell of the whole supply, summed from the `all` of these rows, equal
  the page's legends: 1d +54,914 / −54,811; 7d +329,997 / −327,019; 30d +1,134,837 / −1,121,241.
- **Note:** the 90d file's legend says "net of what is shown". It was written at 06:04Z (14:04
  local time); the oracle was corrected to match the page only afterwards. The page's own text is
  in `expected_B.json`.

## Frontend files generated from this sample

The frontend samples in
`integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/` are generated by these
commands (Tasks 3 and 4 of `docs/features/btc-onchain-perp/PLAN-SR3-4.md`). Run them from the
repository root.

Task 3, from `../../costflow_sample.py`: `cost-flow-sample-0512.json` (S1, this sample at 05:12),
`cost-flow-sample.json` (S2, the 06:04 snapshot rebuilt from the oracle rows) and
`cost-flow-crosscheck.json`.

```sh
cd services/analytics && ../../.venv-foundation/bin/python -c 'import sys
sys.path.insert(0, "tests/onchain")
import costflow_sample as s
out = "../../integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse"
for name, render in (("cost-flow-sample-0512.json", s.render_sample_0512),
                     ("cost-flow-sample.json", s.render_sample_0604),
                     ("cost-flow-crosscheck.json", s.render_crosscheck)):
    open(f"{out}/{name}", "w").write(render())'
```

- S2's reasons `urpd_missing:all:lin200`, `urpd_missing:sth:lin200` and
  `urpd_missing:lth:lin200` are part of how the sample is built: the oracle kept no $200 data.
- `cost-flow-crosscheck.json` holds `math.exp` results, so its last bits depend on the platform's
  libm. It was generated on macOS, arm64, with Python 3.14.6 from `.venv-foundation`.

Task 4: `cost-flow-expected.json`, holding the page's Chart 3 sweep as its string
(`chart3_page`), the page's Chart 4 readings (`chart4_page`) and stage A (`chart3_stage_a`), each
unchanged.

```sh
python3 -I -c 'import json,sys
v, f, out = sys.argv[1:]
data = {"chart3_page": json.load(open(f"{v}/sr3/sweep-expected.json")),
        "chart4_page": json.load(open(f"{v}/sr4/expected_B.json")),
        "chart3_stage_a": json.load(open(f"{f}/expected_chart3.json"))}
open(out, "w").write(json.dumps(data, separators=(",", ":")) + "\n")' \
  "$R/verification-2026-10-19/verify" services/analytics/tests/onchain/fixtures/brk-2026-10-19T0512Z-costflow \
  integrations/wealthfolio/overlay/apps/frontend/src/features/wheelhouse/cost-flow-expected.json
```

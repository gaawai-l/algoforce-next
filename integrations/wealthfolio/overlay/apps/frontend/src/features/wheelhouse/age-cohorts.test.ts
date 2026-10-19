import { expect, it } from "vitest";
import {
  BANDS12,
  DEFAULT_AGE_CHOICE,
  ageAxis,
  ageTip,
  bandsFor,
  buildAgeRows,
  fmtAge,
  fmtShare,
  isShown,
  legendValue,
  priceAxis,
  toggleBand,
  withDetail,
  withSolo,
  type AgeChoice,
  type AgeRow,
  type Detail,
} from "./age-cohorts";
import expected from "./age-cohorts-expected.json";
import { ageCohortsSchema } from "./onchain-contract";
import raw from "./age-cohorts-sample.json";
import { si } from "./sell-side";

// The service's view of a 1000-hour BRK fetch (2026-10-19 15:10Z), and what the original page's
// own chart 2 code, run with d3 on that view, shows for each case (see age-cohorts-expected's
// source).
const sample = ageCohortsSchema.parse(raw);

type Step = [string, string | number | boolean];

function replay(steps: Step[]): AgeChoice {
  let choice = DEFAULT_AGE_CHOICE;
  for (const [kind, value] of steps) {
    if (kind === "detail") choice = withDetail(choice, Number(value) as Detail);
    else if (kind === "solo") choice = withSolo(choice, value as boolean);
    else if (kind === "click") choice = toggleBand(choice, value as number);
    else if (kind === "measure") choice = { ...choice, measure: value as AgeChoice["measure"] };
    else if (kind === "sma") choice = { ...choice, smoothing: value as number };
    else if (kind === "span") choice = { ...choice, span: value as number };
    else if (kind === "scale") choice = { ...choice, scale: value as AgeChoice["scale"] };
  }
  return choice;
}

const tipText = (row: AgeRow, choice: AgeChoice) => {
  const tip = ageTip(row, choice);
  return [
    tip.title,
    ...tip.lines.map((line) => `${line.name} ${line.text}`),
    `profit / loss · total ${tip.total} · spot ${tip.spot}`,
  ];
};

it("covers the original's cases", () => {
  expect(sample.at).toHaveLength(995);
  expect(expected.cases).toHaveLength(54);
});

it.each(expected.cases.map((c, i) => [i, c] as const))(
  "matches the original page, case %i",
  (_, c) => {
    const choice = replay(c.steps as Step[]);
    expect(choice.on).toEqual(c.on);
    const rows = buildAgeRows(sample, choice);
    expect(rows).toHaveLength(c.rows);
    expect(new Date(rows[0].t).toISOString()).toBe(c.first);
    const last = rows[rows.length - 1];
    expect(new Date(last.t).toISOString()).toBe(c.last);

    const axis = ageAxis(rows, choice);
    expect([axis.lo, axis.hi]).toEqual(c.domain);
    expect(axis.ticks).toEqual(c.ticks);
    expect(
      axis.ticks.map((v) =>
        choice.scale === "pct" ? fmtShare(Math.abs(v)) : fmtAge(Math.abs(v), choice.measure),
      ),
    ).toEqual(c.tickText);
    expect(priceAxis(rows).ticks.map((v) => `$${si(v)}`)).toEqual(c.priceTicks);

    const bands = bandsFor(choice.detail);
    expect(bands.map((_, i) => legendValue(last, i, choice, "off"))).toEqual(c.legend);
    const shown = bands.filter((band) => isShown(band, choice.on)).length;
    expect(choice.scale === "pct" && shown < bands.length ? shown : null).toBe(
      c.note === null ? null : Number(/of the (\d+) visible/.exec(c.note)?.[1]),
    );
    let cells = 0;
    for (const row of rows)
      bands.forEach((band, i) => {
        if (!isShown(band, choice.on)) return;
        if (row.p[i] > 0) cells += 1;
        if (row.l[i] > 0) cells += 1;
      });
    expect(cells).toBe(c.cells);

    expect(tipText(last, choice)).toEqual(c.tipLast);
    expect(tipText(rows[Math.floor(rows.length / 2)], choice)).toEqual(c.tipMid);
  },
);

it("names the twelve bands youngest first and folds them into six", () => {
  expect(BANDS12).toHaveLength(12);
  expect(bandsFor(6).map((band) => band.name)).toEqual([
    "<1w",
    "1w–1m",
    "1m–6m",
    "6m–2y",
    "2y–5y",
    "5y+",
  ]);
  expect(bandsFor(6).flatMap((band) => band.src)).toEqual([...BANDS12.keys()]);
});

it("never hides the last band shown, and re-bands to all on or the first band alone", () => {
  let choice = DEFAULT_AGE_CHOICE;
  for (let band = 0; band < 6; band += 1) choice = toggleBand(choice, band);
  // The sixth click is refused: 5y+ is the only band left.
  expect(bandsFor(6).map((band) => isShown(band, choice.on))).toEqual([
    false,
    false,
    false,
    false,
    false,
    true,
  ]);
  expect(withDetail(choice, 12).on).toEqual(new Array(12).fill(true));
  const solo = withSolo(choice, true);
  expect(solo.on).toEqual([...new Array(9).fill(false), true, true, true]);
  expect(withDetail(solo, 12).on).toEqual([true, ...new Array(11).fill(false)]);
  expect(withSolo(solo, false).on).toEqual(new Array(12).fill(true));
});

it("keeps no row and draws no zero for an unavailable view", () => {
  const empty = ageCohortsSchema.parse({
    ...raw,
    data_state: "unavailable",
    forming_at: null,
    last_at: null,
    at: [],
    price: [],
    pnl: { profit: [], loss: [] },
    volb: { profit: [], loss: [] },
    volu: { profit: [], loss: [] },
  });
  expect(buildAgeRows(empty, DEFAULT_AGE_CHOICE)).toEqual([]);
});

it("refuses bands that do not line up with the hours", () => {
  const short = {
    ...raw,
    pnl: { ...raw.pnl, loss: raw.pnl.loss.map((band, i) => (i === 3 ? band.slice(1) : band)) },
  };
  expect(ageCohortsSchema.safeParse(short).success).toBe(false);
  const eleven = { ...raw, volb: { ...raw.volb, profit: raw.volb.profit.slice(1) } };
  expect(ageCohortsSchema.safeParse(eleven).success).toBe(false);
});

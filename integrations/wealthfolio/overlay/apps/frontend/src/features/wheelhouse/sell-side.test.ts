import { describe, expect, it } from "vitest";
import { phrase } from "./i18n";
import { sellSideSchema, type SellSideView } from "./onchain-contract";
import expected from "./sell-side-expected.json";
import sample from "./sell-side-sample.json";
import {
  LEGS,
  buildRows,
  fmtBtc,
  fmtPct,
  fmtUsd,
  fmtVal,
  footLine,
  footTime,
  niceDomain,
  si,
  sma,
  ticks,
  type Choice,
  type Leg,
  type Measure,
} from "./sell-side";

// The local service's sell side for the 2026-10-19 05:30Z golden fetch: every kept hour.
const view = sellSideSchema.parse(sample);

const choice = (overrides: Partial<Choice> = {}): Choice => ({
  measure: "pnl",
  exclude: "x24",
  smoothing: 24,
  span: 720,
  shown: LEGS,
  ...overrides,
});

const tiny = (legs: Partial<Record<Leg, number[]>>, hours = 4): SellSideView => {
  const at = Array.from({ length: hours }, (_, h) =>
    new Date(Date.UTC(2026, 0, 1, h)).toISOString(),
  );
  const column = (leg: Leg) => legs[leg] ?? at.map(() => 1);
  const measure = {
    lth_profit: column("LP"),
    lth_loss: column("LL"),
    sth_profit: column("SP"),
    sth_loss: column("SL"),
    sth_profit_x1: column("SP"),
    sth_loss_x1: column("SL"),
    sth_profit_x24: column("SP"),
    sth_loss_x24: column("SL"),
  };
  return {
    ...view,
    at,
    price: at.map((_, h) => 100 + h),
    pnl: measure,
    volb: measure,
    volu: measure,
  };
};

describe("sell-side rows", () => {
  it("smooths with a trailing mean and leaves the warm-up rows out", () => {
    expect(sma([1, 2, 3, 4], 2)).toEqual([undefined, 1.5, 2.5, 3.5]);
    expect(sma([1, 2, 3], 1)).toEqual([1, 2, 3]);
  });

  it("keeps only rows whose shown legs add up to more than zero", () => {
    const rows = buildRows(
      tiny({ LP: [1, 0, 2, 3], LL: [0, 0, 0, 0], SP: [0, 0, 0, 0], SL: [1, 0, 0, 0] }),
      choice({ smoothing: 1 }),
    );
    expect(rows.map((row) => row.tot)).toEqual([2, 2, 3]);
    const lthOnly = buildRows(
      tiny({ LP: [0, 0, 2, 3], SL: [1, 1, 1, 1] }),
      choice({ smoothing: 1, shown: ["LP"] }),
    );
    expect(lthOnly.map((row) => row.tot)).toEqual([2, 3]);
  });

  it("takes the span in rows, not in hours", () => {
    const rows = buildRows(tiny({}, 10), choice({ smoothing: 3, span: 4 }));
    expect(rows.map((row) => new Date(row.t).getUTCHours())).toEqual([6, 7, 8, 9]);
  });

  it("marks a row contiguous by the payload's hours, not by the rows kept", () => {
    const base = tiny({ LP: [1, 0, 1, 1, 1], LL: [0, 0, 0, 0, 0], SP: [0, 0, 0, 0, 0], SL: [0, 0, 0, 0, 0] }, 5);
    // Hour 1 has no positive total and is left out; hour 4 follows a missing hour.
    const at = [...base.at.slice(0, 3), base.at[4], new Date(Date.UTC(2026, 0, 1, 6)).toISOString()];
    const rows = buildRows({ ...base, at }, choice({ smoothing: 1 }));
    expect(rows.map((row) => [new Date(row.t).getUTCHours(), row.contig])).toEqual([
      [0, true],
      [2, true],
      [4, false],
      [6, false],
    ]);
  });

  it("reads the short-term legs without the excluded coins", () => {
    const base = tiny({});
    const withX1 = {
      ...base,
      pnl: { ...base.pnl, sth_profit_x1: [5, 5, 5, 5], sth_profit: [9, 9, 9, 9] },
    };
    const [plain] = buildRows(withX1, choice({ smoothing: 1, exclude: "" })).slice(-1);
    const [x1] = buildRows(withX1, choice({ smoothing: 1, exclude: "x1" })).slice(-1);
    expect(plain.vals.SP).toBe(9);
    expect(x1.vals.SP).toBe(5);
  });
});

describe("sell-side golden sample", () => {
  it("parses as the contract", () => {
    expect(view.at).toHaveLength(995);
    expect(view.pnl.lth_profit).toHaveLength(995);
  });

  for (const c of expected.cases) {
    const name = `${c.measure} ${c.exclude || "off"} ${c.smoothing}h ${c.span} [${c.shown.join(",")}]`;
    it(`matches the original page: ${name}`, () => {
      const shown = c.shown as Leg[];
      const chosen = choice({
        measure: c.measure as Measure,
        exclude: c.exclude as Choice["exclude"],
        smoothing: c.smoothing,
        span: c.span,
        shown,
      });
      const rows = buildRows(view, chosen);
      expect(rows).toHaveLength(c.rows);
      expect(new Date(rows[0].t).toISOString().slice(0, 13)).toBe(c.first);
      const last = rows[rows.length - 1];
      expect(
        LEGS.map((leg) =>
          shown.includes(leg) ? fmtPct(last.vals[leg] / last.tot) : "off",
        ),
      ).toEqual(c.legendA);
      expect(
        LEGS.map((leg) =>
          shown.includes(leg) ? fmtVal(last.vals[leg], c.measure as Measure) : "off",
        ),
      ).toEqual(c.legendB);
      expect(footLine((key, vars) => phrase("en", key, vars), last, chosen)).toBe(c.foot);
      expect(`$${Math.round(last.px).toLocaleString("en-US")}`).toBe(c.price);
      const peak = Math.max(...rows.map((row) => row.tot));
      const [, top] = niceDomain(0, peak || 1);
      expect(top).toBe(c.top);
      const label = (v: number) => (c.measure === "volb" ? si(v) : `$${si(v)}`);
      expect(ticks(0, top, 5).map(label)).toEqual(c.ticks);
    });
  }
});

describe("sell-side formats", () => {
  it("formats amounts like the original page", () => {
    expect(fmtUsd(780_288.4)).toBe("$780,288");
    expect(fmtUsd(5_563_000)).toBe("$5.6M");
    expect(fmtUsd(1_163_000_000)).toBe("$1.16B");
    expect(fmtBtc(45.94)).toBe("45.9 BTC");
    expect(fmtBtc(14_119.4)).toBe("14,119 BTC");
    expect(fmtPct(0.5694)).toBe("56.9%");
  });

  it("labels axes with SI prefixes and B for billions", () => {
    expect(si(0)).toBe("0");
    expect(si(20_000_000)).toBe("20M");
    expect(si(1_500_000_000)).toBe("1.5B");
    expect(si(2_500)).toBe("2.5k");
    expect(si(80_000)).toBe("80k");
  });

  it("nices the domain with ten steps and ticks it with five", () => {
    expect(niceDomain(0, 96_370_000)).toEqual([0, 100_000_000]);
    expect(niceDomain(0, 109_200_000)).toEqual([0, 110_000_000]);
    expect(ticks(0, 110_000_000, 5)).toEqual([
      0, 20_000_000, 40_000_000, 60_000_000, 80_000_000, 100_000_000,
    ]);
  });

  it("writes the time as the original foot does", () => {
    expect(footTime(Date.UTC(2026, 9, 19, 5))).toBe("19 Oct 2026 · 05:00");
  });
});

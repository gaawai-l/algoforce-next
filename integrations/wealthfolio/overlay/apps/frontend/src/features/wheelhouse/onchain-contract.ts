import { z } from "zod";
import type { components } from "./api-schema";

export type CycleView = components["schemas"]["CycleView"];
export type LevelsView = components["schemas"]["LevelsView"];
export type SellerPressureView = components["schemas"]["SellerPressureView"];

const time = z.string().datetime({ offset: true });
const day = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const dataState = z.enum(["fresh", "stale", "unavailable"]);
const cycleState = z.enum([
  "advance",
  "breakout",
  "pressure",
  "repair",
  "breakdown",
  "capitulation",
]);

export const cycleViewSchema: z.ZodType<CycleView, z.ZodTypeDef, unknown> =
  z.object({
    data_state: dataState,
    reasons: z.array(z.string()),
    refreshing: z.boolean(),
    forming_at: time.nullable(),
    as_of: day.nullable(),
    state: cycleState.nullable(),
    since: day.nullable(),
    day: z.number().int().nullable(),
    components: z.array(
      z.object({
        name: z.enum(["depth", "pvs", "spread"]),
        value: z.number(),
        deadband: z.number(),
        supports: z.boolean(),
      }),
    ),
    episodes: z.array(
      z.object({
        state: cycleState,
        start: day,
        end: day,
        days: z.number().int(),
      }),
    ),
    changes: z.number().int().nullable(),
    brk_version: z.string().nullable(),
  });

const pressureDataState = z.enum(["fresh", "delayed", "stale", "unavailable"]);
const pressureLevels = z.object({
  p95: z.number().nullable(),
  p75: z.number().nullable(),
  n: z.number().int(),
});
const pressurePoint = z.object({ at: time, value: z.number() });

export const levelsViewSchema: z.ZodType<LevelsView, z.ZodTypeDef, unknown> =
  z.object({
    data_state: dataState,
    reasons: z.array(z.string()),
    refreshing: z.boolean(),
    forming_at: time.nullable(),
    as_of: time.nullable(),
    urpd_date: day.nullable(),
    onchain_close: z.number().nullable(),
    lines: z.array(
      z.object({
        name: z.enum([
          "true_mean",
          "short_term",
          "average",
          "long_term",
          "median",
        ]),
        price: z.number(),
      }),
    ),
    brk_version: z.string().nullable(),
  });

export const sellerPressureSchema: z.ZodType<
  SellerPressureView,
  z.ZodTypeDef,
  unknown
> = z.object({
  data_state: pressureDataState,
  reasons: z.array(z.string()),
  refreshing: z.boolean(),
  forming_at: time.nullable(),
  last_at: time.nullable(),
  loss: z.array(z.object({ at: time, lth: z.number(), sth: z.number() })),
  share: z.array(pressurePoint),
  supply: z.array(pressurePoint),
  price: z.array(pressurePoint),
  loss_levels: pressureLevels.nullable(),
  share_levels: pressureLevels.nullable(),
  supply_levels: pressureLevels.nullable(),
  xgap: z.number().int().nullable(),
  qc: z.array(z.enum(["hour_gap", "intraday_legs", "sth_supply"])),
  brk_version: z.string().nullable(),
});

// Hand-written payloads shared by contract and view tests. The cycle components and the
// breakout episode follow the 2026-10-16 fixture result: depth = 100*ln(W/TMM), spread =
// 100*ln(STH/TMM), pvs = depth - spread, and supports = sign matches the state's expected sign
// (breakout expects depth +, pvs +, spread -). The sample lists 2 episodes while `changes` is 48;
// the real service has changes = len(episodes) - 1 with the full history.
export const cycleSample: CycleView = {
  data_state: "fresh",
  reasons: [],
  refreshing: false,
  forming_at: "2026-10-16T00:00:00+00:00",
  as_of: "2026-10-16",
  state: "breakout",
  since: "2026-09-23",
  day: 24,
  components: [
    { name: "depth", value: 6.46, deadband: 7.0, supports: true },
    { name: "pvs", value: 10.43, deadband: 6.8, supports: true },
    { name: "spread", value: -3.96, deadband: 1.25, supports: true },
  ],
  episodes: [
    { state: "repair", start: "2026-08-25", end: "2026-09-22", days: 29 },
    { state: "breakout", start: "2026-09-23", end: "2026-10-16", days: 24 },
  ],
  changes: 48,
  brk_version: "0.1.0",
};

// The line prices are illustrative, not a fixture result.
export const levelsSample: LevelsView = {
  data_state: "fresh",
  reasons: [],
  refreshing: false,
  forming_at: "2026-10-16T00:00:00+00:00",
  as_of: "2026-10-16T00:00:00+00:00",
  urpd_date: "2026-10-16",
  onchain_close: 112345.67,
  lines: [
    { name: "true_mean", price: 98100.5 },
    { name: "short_term", price: 106200.25 },
    { name: "average", price: 71500.0 },
    { name: "long_term", price: 54300.75 },
    { name: "median", price: 63400.1 },
  ],
  brk_version: "0.1.0",
};

const PRESSURE_POINTS = 2200;
const HOUR_MS = 3_600_000;
const PRESSURE_LAST_AT = Date.parse("2026-10-16T08:00:00Z");

// Synthetic hourly series for tests and previews, not a service result. Every value is positive
// and smooth; only the last point and the three level triples carry the 2026-10-16 fixture
// parity values (the loss/share/supply results of the original v1 rules). A factory, so callers
// that slice or mutate the arrays never share state.
export function pressureSample(): SellerPressureView {
  const loss: SellerPressureView["loss"] = [];
  const share: SellerPressureView["share"] = [];
  const supply: SellerPressureView["supply"] = [];
  const price: SellerPressureView["price"] = [];
  for (let i = 0; i < PRESSURE_POINTS; i += 1) {
    const last = i === PRESSURE_POINTS - 1;
    const at = new Date(
      PRESSURE_LAST_AT - (PRESSURE_POINTS - 1 - i) * HOUR_MS,
    ).toISOString();
    const slow = Math.sin(i / 90);
    const fast = Math.sin(i / 7);
    loss.push({
      at,
      lth: last ? 1_983_300 : 2_500_000 + 1_200_000 * slow + 300_000 * fast,
      sth: last ? 8_540_500 : 12_000_000 + 6_000_000 * slow + 800_000 * fast,
    });
    share.push({
      at,
      value: last ? 0.41893330324776934 : 0.3 + 0.12 * slow + 0.02 * fast,
    });
    supply.push({
      at,
      value: last ? 0.2957342245796155 : 0.28 + 0.01 * slow + 0.002 * fast,
    });
    price.push({
      at,
      value: 100_000 + 8_000 * slow + 600 * fast + i * 3,
    });
  }
  const lastAt = loss[loss.length - 1].at;
  return {
    data_state: "fresh",
    reasons: [],
    refreshing: false,
    forming_at: lastAt,
    last_at: lastAt,
    loss,
    share,
    supply,
    price,
    loss_levels: { p95: 41_345_525, p75: 10_050_150, n: 716 },
    share_levels: {
      p95: 0.5611976039771673,
      p75: 0.22150410301296825,
      n: 716,
    },
    supply_levels: {
      p95: 0.38687086545521404,
      p75: 0.26151208272764137,
      n: 716,
    },
    xgap: 2,
    qc: [],
    brk_version: "0.1.0",
  };
}

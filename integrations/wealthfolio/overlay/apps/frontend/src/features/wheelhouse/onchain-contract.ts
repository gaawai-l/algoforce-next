import { z } from "zod";
import type { components } from "./api-schema";

export type CycleView = components["schemas"]["CycleView"];
export type LevelsView = components["schemas"]["LevelsView"];

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

// Hand-written payloads shaped like the service responses; shared by contract and view tests.
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
    { name: "depth", value: 0.042, deadband: 0.01, supports: true },
    { name: "pvs", value: 0.018, deadband: 0.01, supports: true },
    { name: "spread", value: -0.003, deadband: 0.01, supports: false },
  ],
  episodes: [
    { state: "repair", start: "2026-08-30", end: "2026-09-22", days: 24 },
    { state: "breakout", start: "2026-09-23", end: "2026-10-16", days: 24 },
  ],
  changes: 48,
  brk_version: "0.1.0",
};

export const levelsSample: LevelsView = {
  data_state: "fresh",
  reasons: [],
  refreshing: false,
  forming_at: "2026-10-16T00:00:00+00:00",
  as_of: "2026-10-16T00:00:00+00:00",
  urpd_date: "2026-10-15",
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

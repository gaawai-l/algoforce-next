import { z } from "zod";
import type { components } from "./api-schema";

export type MarketCycle = components["schemas"]["MarketCycle"];
export type CycleState = components["schemas"]["CycleStates"]["state"];
export type CycleZone = components["schemas"]["CycleIndex"]["zone"];

const day = z.string().date();
const state = z.enum([
  "advance",
  "breakout",
  "pressure",
  "repair",
  "breakdown",
  "capitulation",
]);

export const marketCycleSchema: z.ZodType<MarketCycle, z.ZodTypeDef, unknown> =
  z.object({
    source: z.literal("bitview"),
    status: z.enum(["fresh", "stale", "unavailable"]),
    checked_at: z.string().datetime({ offset: true }),
    as_of: day.nullable(),
    states: z
      .object({
        state,
        since: day,
        days: z.number().int(),
        changes: z.number().int(),
        depth: z.number(),
        spread: z.number(),
        multiplier: z.number().int(),
        stats: z.array(
          z.object({
            state,
            runs: z.number().int(),
            days: z.number().int(),
            mean_days: z.number().nullable(),
            median_days: z.number().nullable(),
            max_days: z.number().int().nullable(),
          }),
        ),
      })
      .nullable(),
    index: z
      .object({
        components: z.object({
          unrealized: z.number(),
          realized: z.number(),
          supply: z.number(),
          young_vs_seasoned: z.number(),
        }),
        composite: z.number(),
        zone: z.enum([
          "low",
          "transition_low",
          "mid",
          "transition_high",
          "top",
        ]),
        change: z.record(z.number().nullable()),
      })
      .nullable(),
    pressure: z
      .object({
        value: z.number(),
        history: z.array(z.object({ day, value: z.number() })),
        warn: z.number(),
        confirm: z.number(),
        thresholds_confirmed: z.boolean(),
        stage: z.enum(["none", "warning", "confirmed"]),
      })
      .nullable(),
    error: z.string().nullable(),
  });

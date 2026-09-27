import { z } from "zod";
import type { components } from "./api-schema";
import { demarkConfigSchema } from "./demark-contract";

export type MarketContext = components["schemas"]["MarketContext"];
export type TimeframeContext = MarketContext["timeframes"][number];
export type RegimeValue = MarketContext["intraday"]["value"];

const time = z.string().datetime({ offset: true });
const price = z.string().regex(/^-?\d+(?:\.\d+)?$/);
const int = z.number().int();
const side = z.enum(["buy", "sell"]);
const trend = z.enum(["up", "down"]);
const level = int.min(1).max(5);
const timeframe = z.enum(["5m", "15m", "1h", "4h", "1d"]);
const regime = z.object({
  anchor: timeframe,
  value: z.enum(["decay", "rev", "pump", "none", "unavailable"]),
});
const summary = z.object({
  side,
  trend,
  phase: z.enum(["setup", "countdown"]),
  step: int,
  target: z.union([z.literal(9), z.literal(13)]),
  setup_step: int,
  countdown_step: int,
  rounds: z.array(
    z.object({
      side,
      trend,
      setup: int,
      countdown: int,
      setup9_at: time.nullable(),
      qualified13_at: time.nullable(),
    }),
  ),
  last_signal: z
    .object({ kind: z.union([z.literal(9), z.literal(13)]), at: time, side })
    .nullable(),
  prev: z
    .object({ side, countdown: int, qualified: z.boolean(), bars_ago: int })
    .nullable(),
  second: z
    .object({ side, trend, step: int, setup9_at: time.nullable() })
    .nullable(),
  bars_since_qualified13: int.nullable(),
  setup_run: z.object({
    start: time,
    side,
    count: int,
    active: z.boolean(),
    completed: z.boolean(),
  }),
  risk: z.object({
    risk9: price.nullable(),
    risk9_at: time.nullable(),
    setup_close: price.nullable(),
    risk_level: price.nullable(),
    risk13_at: time.nullable(),
    provisional: z.boolean(),
    close13: price.nullable(),
    tdst: price.nullable(),
    next_bar_needs: z
      .object({ direction: z.enum(["above", "below"]), price })
      .nullable(),
  }),
  as_of: time,
  close: price,
});

export const marketContextSchema: z.ZodType<
  MarketContext,
  z.ZodTypeDef,
  unknown
> = z.object({
  source: z.enum(["fixture", "binance"]),
  symbol: z.enum(["BTCUSDT", "ETHUSDT"]),
  checked_at: time,
  market_at: time,
  knowledge_at: time,
  mode: z.enum(["as_known", "retrospective"]),
  config: demarkConfigSchema,
  window: int,
  timeframes: z.array(
    z.object({
      timeframe,
      status: z.enum(["fresh", "delayed", "stale", "unavailable", "simulated"]),
      bars_used: int,
      history_complete: z.boolean(),
      history_gapped: z.boolean(),
      last_closed_at: time.nullable(),
      summary: summary.nullable(),
      state: z
        .object({
          s9: z.enum(["up", "down", "none"]),
          s13: z.boolean(),
          carry13: z.boolean(),
          countdown: int,
          setup9_at: time.nullable(),
          qualified13_at: time.nullable(),
          setup9_seconds_ago: int.nullable(),
          qualified13_seconds_ago: int.nullable(),
          beyond_risk9: z.boolean().nullable(),
        })
        .nullable(),
      signals: z.array(
        z.object({
          n: z.union([z.literal(1), z.literal(2)]),
          side,
          active: z.boolean(),
          price: price.nullable(),
          base_level: level.nullable(),
          intraday_level: level.nullable(),
          swing_level: level.nullable(),
        }),
      ),
      new_trend: z
        .object({
          present: z.boolean(),
          trend,
          step: int,
          confirmed: z.boolean(),
          seconds: int.nullable(),
        })
        .nullable(),
    }),
  ),
  intraday: regime,
  swing: regime,
});

import { z } from "zod";
import type { components } from "./api-schema";
import sample from "./perp-states-sample.json";

export type PerpStatesView = components["schemas"]["PerpStatesView"];
export type PerpsStatus = components["schemas"]["PerpsStatus"];
export type PerpBlock = components["schemas"]["Block"];
export type PerpTable = components["schemas"]["Table"];
export type PerpState = components["schemas"]["TableRow"]["state"];
export type PerpCollector = components["schemas"]["CollectorStatus"];

const time = z.string().datetime({ offset: true });
const int = z.number().int();
const dataState = z.enum(["fresh", "delayed", "stale", "unavailable"]);
const perpState = z.enum([
  "shortsq",
  "longsq",
  "shortun",
  "longun",
  "longbd",
  "shortbd",
  "spot",
  "chop",
]);
const verdict = z.enum(["ok", "inverted", "pending"]);

const blockSchema = z.object({
  t0: time,
  t1: time,
  buckets: int,
  forming: z.boolean(),
  liq_covered: z.boolean(),
  delta_covered: z.boolean(),
  covered: z.boolean(),
  dpx: z.number(),
  doi: z.number(),
  delta: z.number(),
  lliq: z.number(),
  sliq: z.number(),
  imputed: z.object({
    dpx: z.boolean(),
    doi: z.boolean(),
    sums: z.boolean(),
  }),
  state: perpState.nullable(),
  price_close: z.number().nullable(),
  oi_close: z.number().nullable(),
  delta_sum: z.number().nullable(),
  lliq_sum: z.number().nullable(),
  sliq_sum: z.number().nullable(),
});
const tailSchema = z.object({
  t0: time,
  t1: time,
  price_close: z.number().nullable(),
  oi_close: z.number().nullable(),
  delta_sum: z.number().nullable(),
  lliq_sum: z.number().nullable(),
  sliq_sum: z.number().nullable(),
});
const thresholdsSchema = z.object({
  s_liq: z.number(),
  l_liq: z.number(),
  oi: z.number(),
  px: z.number(),
  n_liq: int,
  n_all: int,
});
const tableSchema = z.object({
  show_days: int,
  view_from: time,
  judged: int,
  in_view: int,
  rows: z.array(
    z.object({
      state: perpState,
      count: int,
      share: int.nullable(),
      max_move: z.number().nullable(),
      run_blocks: int.nullable(),
    }),
  ),
  latest: perpState.nullable(),
  latest_uncovered: z.boolean(),
});
const collectorSchema = z.object({
  stream: z.enum(["binance_liq", "bybit_liq", "bybit_trades"]),
  live: z.boolean(),
  last_proof: time.nullable(),
  down_since: time.nullable(),
  covered_days: z.number(),
  since: time.nullable(),
});
const directionCheckSchema = z.object({
  verdict,
  samples: int,
  down: int,
  long_share: z.number().nullable(),
});

export const perpStatesViewSchema: z.ZodType<
  PerpStatesView,
  z.ZodTypeDef,
  unknown
> = z.object({
  exchange: z.enum(["all", "binance", "bybit"]),
  window: z.enum(["4h", "8h"]),
  data_state: dataState,
  reasons: z.array(z.string()),
  computed_at: time.nullable(),
  last: time.nullable(),
  thresholds: thresholdsSchema.nullable(),
  blocks: z.array(blockSchema),
  tail: tailSchema.nullable(),
  tables: z.array(tableSchema),
  covered_days: z.number().nullable(),
  collecting: z.boolean().nullable(),
  qc: z.array(z.string()),
  series_missing: z.array(z.string()),
  collectors: z.array(collectorSchema),
});

export const perpsStatusSchema: z.ZodType<PerpsStatus, z.ZodTypeDef, unknown> =
  z.object({
    last_run_at: time.nullable(),
    last_error: z.string().nullable(),
    hosts: z.array(
      z.object({
        host: z.string(),
        last_success: time.nullable(),
        error: z.string().nullable(),
        backoff_until: time.nullable(),
      }),
    ),
    collectors: z.array(collectorSchema),
    direction: verdict,
    direction_check: z
      .object({
        binance: directionCheckSchema,
        bybit: directionCheckSchema,
        bybit_qty: z.object({
          events: int,
          min_qty: z.number().nullable(),
          min_notional: z.number().nullable(),
          max_notional: z.number().nullable(),
          notional_in_range: z.boolean().nullable(),
          min_qty_matches: z.boolean().nullable(),
        }),
      })
      .nullable(),
  });

export type PerpStatesVariant = "full" | "collecting" | "uncovered" | "qc";

const BLOCKS_PER_DAY = 6; // 4h blocks
// 20 whole blocks and the forming one: three days and a half, short of the 7 that end collecting.
const COLLECTING_BLOCKS = 21;

// Whole percents adding up to 100 by largest remainder, ties in row order (the service's rule).
function percents(counts: number[]): number[] {
  const total = counts.reduce((sum, count) => sum + count, 0);
  const raw = counts.map((count) => (100 * count) / total);
  const whole = raw.map(Math.floor);
  let left = 100 - whole.reduce((sum, value) => sum + value, 0);
  const order = raw
    .map((_, k) => k)
    .sort((a, b) => raw[b] - whole[b] - (raw[a] - whole[a]));
  for (const k of order) {
    if (left > 0 && raw[k] - whole[k] > 0) {
      whole[k] += 1;
      left -= 1;
    }
  }
  return whole;
}

// The thresholds keep the full sample's values; they are not recomputed over the 21 blocks.
// Nothing is judged while collecting, so they decide nothing here.
function collecting(view: PerpStatesView): PerpStatesView {
  const blocks = view.blocks
    .slice(-COLLECTING_BLOCKS)
    .map((block) => ({ ...block, state: null }));
  const coveredDays =
    blocks.filter((block) => block.covered).length / BLOCKS_PER_DAY;
  return {
    ...view,
    reasons: [`collecting:${coveredDays.toFixed(1)}`],
    // The streams started with the first block, so they cover what the view covers.
    collectors: view.collectors.map((collector) => ({
      ...collector,
      covered_days: coveredDays,
      since: blocks[0].t0,
    })),
    thresholds: view.thresholds && {
      ...view.thresholds,
      n_liq: blocks.length,
      n_all: blocks.length,
    },
    blocks,
    // The history starts at the first block, so both table views reach back only that far.
    tables: view.tables.map((table) => ({
      ...table,
      view_from: blocks[0].t0,
      judged: 0,
      in_view: blocks.length,
      rows: table.rows.map((row) => ({
        ...row,
        count: 0,
        share: null,
        max_move: null,
        run_blocks: null,
      })),
      latest: null,
    })),
    covered_days: coveredDays,
    collecting: true,
  };
}

function uncover(block: PerpBlock): PerpBlock {
  return {
    ...block,
    liq_covered: false,
    delta_covered: false,
    covered: false,
    delta: 0,
    lliq: 0,
    sliq: 0,
    imputed: { ...block.imputed, sums: true },
    state: null,
    delta_sum: null,
    lliq_sum: null,
    sliq_sum: null,
  };
}

// Every stream went down inside the forming block, after a past gap over the oldest block.
const DOWN_SINCE = "2026-10-17T09:30:00Z";
// From the first coverage to the gap (32 h), and from the gap to DOWN_SINCE (717.5 h).
const COVERED_DAYS_AFTER_GAP = (32 + 717.5) / 24;

// The oldest block (outside both table views) and the forming latest one lose their coverage.
// Counts and shares are redone the way the service recounts the tables; the best moves and runs
// of the other states are unaffected.
function uncovered(view: PerpStatesView): PerpStatesView {
  const latest = view.blocks.at(-1);
  if (!latest?.state) throw new Error("the sample has no judged latest block");
  const state = latest.state;
  return {
    ...view,
    reasons: view.collectors.map(
      (collector) => `collector_down:${collector.stream}`,
    ),
    collectors: view.collectors.map((collector) => ({
      ...collector,
      live: false,
      last_proof: DOWN_SINCE,
      down_since: DOWN_SINCE,
      covered_days: COVERED_DAYS_AFTER_GAP,
    })),
    thresholds: view.thresholds && {
      ...view.thresholds,
      n_liq: view.thresholds.n_liq - 2,
    },
    blocks: view.blocks.map((block, k) =>
      k === 0 || k === view.blocks.length - 1 ? uncover(block) : block,
    ),
    tables: view.tables.map((table) => {
      const counts = table.rows.map(
        (row) => row.count - (row.state === state ? 1 : 0),
      );
      const shares = percents(counts);
      return {
        ...table,
        judged: table.judged - 1,
        rows: table.rows.map((row, k) => ({
          ...row,
          count: counts[k],
          share: shares[k],
        })),
        latest: null,
        latest_uncovered: true,
      };
    }),
    covered_days:
      view.covered_days === null
        ? null
        : view.covered_days - 2 / BLOCKS_PER_DAY,
  };
}

// Test-only: the service's own all-venues 4h view (written by the Python tests from a synthetic
// grid), with variants derived from it. Runtime code must not use it: a missing view is shown
// as missing, never as this data.
export function perpStatesSample(
  variant: PerpStatesVariant = "full",
): PerpStatesView {
  // Parsing builds new objects and arrays all the way down, so no variant touches the import.
  const view = perpStatesViewSchema.parse(sample);
  switch (variant) {
    case "collecting":
      return collecting(view);
    case "uncovered":
      return uncovered(view);
    case "qc":
      return {
        ...view,
        // The service's order: series by series (missing, then gap), then the archive.
        qc: [
          "gap:binance:oi:3600",
          "missing:bybit:oi",
          "archive_quarantined:1",
        ],
      };
    default:
      return view;
  }
}

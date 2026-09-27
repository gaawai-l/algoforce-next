import { z } from "zod";
import type { components } from "./api-schema";

export type DemarkResult = components["schemas"]["DemarkResult"];
export type DemarkSequence = components["schemas"]["DemarkSequence"];
const time = z.string().datetime({ offset: true });
const price = z.string().regex(/^-?\d+(?:\.\d+)?$/);
export const demarkConfigSchema = z.object({
  variant: z.literal("sequential"),
  ruleset_version: z.literal("wheelhouse-sequential-1"),
  price_flip_required: z.boolean(),
  perfection_policy: z.literal("strict"),
  qualifier_8_vs_5: z.literal(false),
  risk_formula: z.literal("countdown_span_true_extreme_earliest"),
  tdst_breach: z.enum(["true_extreme", "close"]),
  risk_breach: z.enum(["close", "true_extreme"]),
  recycling: z.enum(["range_and_22", "none"]),
  validity_bars: z.number().int().min(1).max(10000).nullable(),
});
export const defaultDemarkConfig: z.infer<typeof demarkConfigSchema> = {
  variant: "sequential",
  ruleset_version: "wheelhouse-sequential-1",
  price_flip_required: true,
  perfection_policy: "strict",
  qualifier_8_vs_5: false,
  risk_formula: "countdown_span_true_extreme_earliest",
  tdst_breach: "true_extreme",
  risk_breach: "close",
  recycling: "range_and_22",
  validity_bars: null,
};
const barRef = z.object({
  revision_id: z.string(),
  open_time: time,
  close_time: time,
  close: price,
});
const side = z.enum(["buy", "sell"]);
const sequence = z.object({
  sequence_id: z.string(),
  side,
  setup_count: z.number().int().min(1).max(9),
  setup_status: z.enum(["forming", "completed", "interrupted"]),
  setup_bars: z.array(barRef),
  setup_perfected: z.boolean().nullable(),
  perfected_at: time.nullable(),
  countdown_count: z.number().int().min(0).max(13),
  countdown_status: z.enum([
    "inactive",
    "active",
    "count13_unqualified",
    "qualified13",
    "cancelled",
    "recycled",
  ]),
  countdown_bars: z.array(barRef),
  countdown_bar8: barRef.nullable(),
  qualification_threshold: price.nullable(),
  qualified_at: time.nullable(),
  confirmation_close: price.nullable(),
  tdst: price.nullable(),
  tdst_source: barRef.nullable(),
  tdst_breached_at: time.nullable(),
  risk_level: price.nullable(),
  risk_source: barRef.nullable(),
  risk_status: z.enum([
    "not_available",
    "valid",
    "invalidated",
    "expired",
    "unknown",
  ]),
  risk_ended_at: time.nullable(),
  continuity: z.enum(["observed", "lost"]),
  bars_since_setup9: z.number().int().nullable(),
  bars_since_qualified13: z.number().int().nullable(),
  elapsed_since_setup9_seconds: z.number().int().nullable(),
  elapsed_since_qualified13_seconds: z.number().int().nullable(),
  next_conditions: z.array(
    z.object({
      field: z.enum(["close", "low", "high"]),
      operator: z.enum(["<", ">", "<=", ">="]),
      threshold: price,
      reference: barRef,
      purpose: z.enum(["setup", "countdown", "qualification13"]),
    }),
  ),
});
export const demarkResultSchema: z.ZodType<DemarkResult> = z.object({
  config: demarkConfigSchema,
  input_hash: z.string(),
  history_start: time.nullable(),
  history_end: time.nullable(),
  history_status: z.enum(["window_only", "gapped", "empty"]),
  status: z.enum(["ready", "warming_up", "unavailable"]),
  warmup_required: z.number().int(),
  sequences: z.array(sequence),
  events: z.array(
    z.object({
      sequence_id: z.string(),
      side,
      kind: z.enum([
        "setup_count",
        "setup_completed",
        "setup_interrupted",
        "perfected",
        "countdown_count",
        "deferred13",
        "qualified13",
        "cancelled",
        "recycled",
        "invalidated",
        "expired",
        "continuity_lost",
      ]),
      bar: barRef,
      count: z.number().int().nullable(),
      reason: z.string(),
    }),
  ),
  qualified13_count: z.number().int(),
  issues: z.array(z.string()),
});

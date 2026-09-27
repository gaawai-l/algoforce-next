import { z } from "zod";
import { demarkConfigSchema, demarkResultSchema } from "./demark-contract";
import type { components } from "./api-schema";

export type ServiceStatus = components["schemas"]["ServiceStatus"];
export type Analysis = components["schemas"]["Analysis"];
export type Workspace = components["schemas"]["Workspace"];
export type Job = components["schemas"]["Job"];
export type JobRequest = components["schemas"]["JobRequest-Input"];
export type Stream = components["schemas"]["Stream-Output"];
export type Rules = components["schemas"]["Rules-Output"];
export type SnapshotSummary = components["schemas"]["SnapshotSummary"];
export type Schedule = components["schemas"]["Schedule"];
export type JobEvent = components["schemas"]["JobEvent"];
export const PREFIX = "/api/wheelhouse/v1";

const time = z.string().datetime({ offset: true });
const decimal = z.string().regex(/^\d+(?:\.\d+)?$/);
const source = z.enum(["fixture", "binance"]);
const state = z.enum(["fresh", "delayed", "stale", "unavailable", "simulated"]);
const streamSchema: z.ZodType<Stream> = z.object({
  source,
  symbol: z.enum(["BTCUSDT", "ETHUSDT"]),
  timeframe: z.enum(["5m", "15m", "1h", "4h", "1d"]),
  venue: z.literal("binance-spot"),
  market_session: z.literal("24/7"),
  timezone: z.literal("UTC"),
  quote_currency: z.literal("USDT"),
  base_currency: z.enum(["BTC", "ETH"]),
  price_encoding: z.literal("decimal_string_18_places"),
});
const rulesSchema: z.ZodType<Rules> = z.object({
  engine_version: z.literal("baseline-v1"),
  window: z.number().int().min(2).max(200),
  demark: demarkConfigSchema.nullable(),
});
const barSchema = z.object({
  open_time: time,
  close_time: time,
  open: decimal,
  high: decimal,
  low: decimal,
  close: decimal,
  volume: decimal.nullable(),
  is_closed: z.boolean(),
});
const storedSchema = z.object({
  revision_id: z.string(),
  revision: z.number().int(),
  fetched_at: time,
  bar: barSchema,
});
const pointSchema = z.object({
  at: time,
  revision_id: z.string(),
  sma: decimal.nullable(),
  prior_high: decimal.nullable(),
  prior_low: decimal.nullable(),
});
export const analysisSchema: z.ZodType<Analysis> = z.object({
  snapshot_id: z.string(),
  input_hash: z.string(),
  stream: streamSchema,
  rules: rulesSchema,
  market_at: time,
  knowledge_at: time,
  fetched_at: time.nullable(),
  closed_bar_time: time.nullable(),
  forming_bar_time: time.nullable(),
  expected_next_close: time.nullable(),
  data_state: state,
  mode: z.enum(["as_known", "retrospective"]),
  warmup_required: z.number().int(),
  warmup_complete: z.boolean(),
  issues: z.array(z.string()),
  bars: z.array(storedSchema),
  points: z.array(pointSchema),
  signal_status: z.literal("not_implemented"),
  demark: demarkResultSchema.nullable(),
});
const jobSchema: z.ZodType<Job> = z.object({
  job_id: z.string(),
  request: z.object({
    kind: z.enum(["refresh", "analyze"]),
    stream: streamSchema,
    rules: rulesSchema,
    market_at: time.nullable(),
    knowledge_at: time.nullable(),
  }),
  state: z.enum(["queued", "running", "retry_wait", "succeeded", "failed"]),
  attempts: z.number().int(),
  created_at: time,
  updated_at: time,
  next_attempt_at: time,
  lease_until: time.nullable(),
  checkpoint_batch_id: z.string().nullable(),
  snapshot_id: z.string().nullable(),
  error_code: z.string().nullable(),
});
const scheduleSchema: z.ZodType<Schedule> = z.object({
  schedule_id: z.string(),
  request: z.object({
    stream: streamSchema,
    rules: rulesSchema,
    enabled: z.boolean(),
  }),
  next_due: time,
});
const workspaceSchema: z.ZodType<Workspace> = z.object({
  stream: streamSchema,
  checked_at: time,
  current_state: state,
  snapshot: analysisSchema.nullable(),
  latest_job: jobSchema.nullable(),
  refresh_job: jobSchema.nullable(),
  schedule: scheduleSchema.nullable(),
});
const summarySchema: z.ZodType<SnapshotSummary> = z.object({
  snapshot_id: z.string(),
  created_at: time,
  market_at: time,
  knowledge_at: time,
  rules: rulesSchema,
  data_state: z.string(),
  mode: z.string(),
  bar_count: z.number().int(),
});
const statusSchema: z.ZodType<ServiceStatus> = z.object({
  service: z.literal("wheelhouse-python"),
  status: z.literal("ready"),
  contract_version: z.literal("1"),
  service_version: z.string(),
  python_version: z.string(),
  checked_at: time,
  read_only: z.literal(true),
  integrations: z.object({
    broker: z.literal("not_connected"),
    market_data: z.enum(["not_connected", "available"]),
    analytics: z.literal("baseline_ready"),
  }),
  capabilities: z.array(z.string()),
});

async function query<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    const timeout = AbortSignal.timeout(5000);
    response = await fetch(PREFIX + path, {
      ...init,
      cache: "no-store",
      signal: init?.signal ? AbortSignal.any([init.signal, timeout]) : timeout,
    });
  } catch {
    throw new Error(
      "Python service did not respond. Check the local workspace and retry.",
    );
  }
  if (!response.ok)
    throw new Error(
      `Python service unavailable (HTTP ${response.status}). No simulated fallback was used.`,
    );
  const parsed = schema.safeParse(await response.json());
  if (!parsed.success)
    throw new Error(
      "Python service contract is incompatible. Update the host and service together.",
    );
  return parsed.data;
}
const params = (stream: Stream) =>
  new URLSearchParams({
    source: stream.source,
    symbol: stream.symbol,
    timeframe: stream.timeframe,
  });
export const getServiceStatus = (signal?: AbortSignal) =>
  query("/status", statusSchema, { signal });
export const getWorkspace = (stream: Stream, signal?: AbortSignal) =>
  query(`/workspace?${params(stream)}`, workspaceSchema, { signal });
export const getSnapshots = (stream: Stream, signal?: AbortSignal) =>
  query(`/snapshots?${params(stream)}`, z.array(summarySchema), { signal });
export const getSnapshot = (id: string, signal?: AbortSignal) =>
  query(`/snapshots/${encodeURIComponent(id)}`, analysisSchema, { signal });
export const getJob = (id: string, signal?: AbortSignal) =>
  query(`/jobs/${encodeURIComponent(id)}`, jobSchema, { signal });
export const getJobEvents = (id: string, signal?: AbortSignal) =>
  query(
    `/jobs/${encodeURIComponent(id)}/events`,
    z.array(z.object({ at: time, state: z.string(), reason: z.string() })),
    { signal },
  );
export const submitJob = (request: JobRequest, key: string) =>
  query("/jobs", jobSchema, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify(request),
  });
export const updateSchedule = (
  stream: Stream,
  rules: Rules,
  enabled: boolean,
) =>
  query("/schedule", scheduleSchema, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stream, rules, enabled }),
  });
export const money = (value: string | null | undefined) =>
  value == null
    ? "Unavailable"
    : Number(value).toLocaleString("en-US", {
        maximumFractionDigits: 2,
        minimumFractionDigits: 2,
      });
export const stamp = (value: string | null | undefined) =>
  value
    ? new Date(value).toISOString().replace("T", " ").slice(0, 19) + " UTC"
    : "Unavailable";

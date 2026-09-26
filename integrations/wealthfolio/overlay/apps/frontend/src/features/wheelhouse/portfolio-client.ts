import { z } from "zod";
import type { components } from "./api-schema";

export type PortfolioWorkspace = components["schemas"]["PortfolioWorkspace"];
export type Instrument = components["schemas"]["Instrument-Input"];
export type LedgerEvent = components["schemas"]["LedgerEvent-Input"];
export type SyncJob = components["schemas"]["SyncJob"];
export type Source = "demo" | "moomoo";
export interface Account {
  source: Source;
  account: string;
  captured_at: string;
}
export interface BrokerAccount {
  account_id: string;
  status: string;
  markets: string[];
  firm: string;
  environment: string;
}
export interface Connection {
  sdk_installed: boolean;
  gateway_reachable: boolean;
  message: string;
  firm: string;
  environment: string;
  host: string;
  port: number;
  read_only: boolean;
  account_verified: boolean;
}
const prefix = "/api/wheelhouse/v1/portfolio";
export async function portfolioRequest<T>(
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(prefix + path, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined
        ? {}
        : {
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(60000),
    cache: "no-store",
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : (data?.message ??
            `Request failed (${response.status}); local data is preserved.`),
    );
  }
  return response.json() as Promise<T>;
}
const decimal = z.string().regex(/^-?\d+(?:\.\d+)?$/);
const time = z.string().datetime({ offset: true });
const instrument = z.object({
  code: z.string(),
  underlying: z.string(),
  kind: z.enum(["stock", "call", "put"]),
  currency: z.string(),
  multiplier: decimal,
  strike: decimal.nullable(),
  expiry: z.string().nullable(),
  source: z.string(),
});
const event = z.object({
  event_id: z.string(),
  cycle_id: z.string(),
  at: time,
  kind: z.enum([
    "buy_open",
    "sell_open",
    "buy_close",
    "sell_close",
    "expire",
    "assign",
    "exercise",
    "cash_settle",
  ]),
  instrument,
  quantity: decimal,
  price: decimal,
  fee: decimal.nullable(),
  source_record_id: z.string().nullable(),
  settlement_record_id: z.string().nullable(),
  roll_group: z.string().nullable(),
  evidence_issues: z.array(z.string()),
  author: z.string(),
  reason: z.string(),
});
export const portfolioSchema: z.ZodType<PortfolioWorkspace> = z.object({
  state: z.enum(["available", "stale", "unavailable", "simulated"]),
  capture: z
    .object({
      source: z.enum(["demo", "moomoo"]),
      account_id: z.string(),
      captured_at: time,
      snapshot_observed_at: time.nullable(),
      base_currency: z.string(),
      positions: z.array(
        z.object({
          code: z.string(),
          quantity: decimal,
          mark: decimal.nullable(),
          observed_at: time,
        }),
      ),
      instruments: z.array(instrument),
      quotes: z.array(
        z.object({
          code: z.string(),
          spot: decimal,
          delta: decimal.nullable(),
          gamma: decimal.nullable(),
          theta: decimal.nullable(),
          vega: decimal.nullable(),
          units: z.enum(["per_share", "per_contract"]),
          theta_basis: z.enum(["day", "year"]),
          vega_basis: z.enum(["percentage_point", "unit_volatility"]),
          observed_at: time,
          source: z.string(),
        }),
      ),
      fx: z.array(
        z.object({
          currency: z.string(),
          to_base: decimal,
          observed_at: time,
          source: z.string(),
        }),
      ),
      raw: z.record(z.unknown()),
      errors: z.record(z.string()),
      history_start: z.string().nullable(),
      history_end: z.string().nullable(),
    })
    .nullable(),
  cycles: z.array(
    z.object({
      cycle: z.object({
        cycle_id: z.string(),
        source: z.enum(["demo", "moomoo"]),
        account_id: z.string(),
        underlying: z.string(),
        currency: z.string(),
        name: z.string(),
        created_at: time,
      }),
      method: z.string(),
      state: z.enum(["empty", "open", "closed", "incomplete"]),
      premium_received: decimal.nullable(),
      premium_paid: decimal.nullable(),
      gross_cash_movement: decimal.nullable(),
      known_fees: decimal,
      net_cash_movement: decimal.nullable(),
      realized_gross: decimal.nullable(),
      realized_net: decimal.nullable(),
      unrealized: decimal.nullable(),
      lots: z.array(
        z.object({
          code: z.string(),
          quantity: decimal,
          entry_price: decimal,
          opening_event_id: z.string(),
        }),
      ),
      events: z.array(event),
      issues: z.array(z.string()),
    }),
  ),
  risk: z
    .object({
      base_currency: z.string(),
      evaluated_at: time,
      state: z.enum(["complete", "partial", "unavailable"]),
      dollar_delta: decimal.nullable(),
      theta_daily: decimal.nullable(),
      vega_point: decimal.nullable(),
      issues: z.array(z.string()),
      exposures: z.array(
        z.object({
          underlying: z.string(),
          currency: z.string(),
          share_delta: decimal.nullable(),
          share_gamma: decimal.nullable(),
          theta_daily: decimal.nullable(),
          vega_point: decimal.nullable(),
          dollar_delta_base: decimal.nullable(),
          issues: z.array(z.string()),
        }),
      ),
    })
    .nullable(),
  records: z.array(z.record(z.unknown())),
  audit: z.array(z.record(z.unknown())),
  issues: z.array(z.string()),
});
export async function portfolioWorkspace(
  source: Source,
  account: string,
): Promise<PortfolioWorkspace> {
  const value = await portfolioRequest<unknown>(
    `/workspace?${new URLSearchParams({ source, account_id: account })}`,
  );
  const parsed = portfolioSchema.safeParse(value);
  if (!parsed.success)
    throw new Error("Portfolio response contract is incompatible");
  return parsed.data;
}
const syncJobSchema: z.ZodType<SyncJob> = z.object({
  job_id: z.string(),
  account_id: z.string(),
  state: z.enum([
    "queued",
    "running",
    "retry_wait",
    "succeeded",
    "partial",
    "failed",
  ]),
  phase: z.enum(["snapshot", "fees"]),
  attempts: z.number().int(),
  total_orders: z.number().int(),
  completed_orders: z.number().int(),
  missing_orders: z.number().int(),
  updated_at: time,
  next_due: time,
  error: z.string().nullable(),
});
export async function currentSync(account: string): Promise<SyncJob | null> {
  const raw = await portfolioRequest<unknown>(
    `/sync-status?${new URLSearchParams({ account_id: account })}`,
  );
  const parsed = syncJobSchema.nullable().safeParse(raw);
  if (!parsed.success)
    throw new Error("Sync response contract is incompatible");
  return parsed.data;
}
export const displayAmount = (value: string | null | undefined) =>
  value == null
    ? "Unavailable"
    : Number(value).toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });

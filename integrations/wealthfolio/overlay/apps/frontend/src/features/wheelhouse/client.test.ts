import { afterEach, describe, expect, it, vi } from "vitest";
import { getServiceStatus } from "./client";

const validResponse = {
  service: "wheelhouse-python",
  status: "ready",
  contract_version: "1",
  service_version: "0.1.0",
  python_version: "3.14.6",
  checked_at: "2026-09-26T00:00:00Z",
  read_only: true,
  integrations: {
    broker: "not_connected",
    market_data: "not_connected",
    analytics: "baseline_ready",
  },
  capabilities: ["service_status"],
};

afterEach(() => vi.unstubAllGlobals());

describe("Wealthfolio → Python contract", () => {
  it("accepts a compatible response without claiming market or broker integration", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(validResponse))),
    );
    const status = await getServiceStatus();
    expect(status.read_only).toBe(true);
    expect(status.integrations.broker).toBe("not_connected");
  });

  it("rejects a responding service with an incompatible contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ ...validResponse, contract_version: "2" }),
          ),
        ),
    );
    await expect(getServiceStatus()).rejects.toThrow("incompatible");
  });

  it("surfaces proxy failures rather than showing connected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("Unavailable", { status: 502 })),
    );
    await expect(getServiceStatus()).rejects.toThrow("HTTP 502");
  });
});

describe("DeMark v1 response compatibility", () => {
  const stream = {
    source: "binance" as const,
    symbol: "BTCUSDT" as const,
    timeframe: "15m" as const,
    venue: "binance-spot" as const,
    market_session: "24/7" as const,
    timezone: "UTC" as const,
    quote_currency: "USDT" as const,
    base_currency: "BTC" as const,
    price_encoding: "decimal_string_18_places" as const,
  };
  const legacyConfig = {
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
  const at = "2026-09-27T15:00:00Z";
  const payload = {
    stream,
    checked_at: at,
    current_state: "fresh",
    latest_job: null,
    refresh_job: null,
    schedule: null,
    snapshot: {
      snapshot_id: "legacy",
      input_hash: "legacy-input",
      stream,
      rules: {
        engine_version: "baseline-v1",
        window: 20,
        demark: legacyConfig,
      },
      market_at: at,
      knowledge_at: at,
      fetched_at: at,
      closed_bar_time: at,
      forming_bar_time: null,
      expected_next_close: at,
      data_state: "fresh",
      mode: "as_known",
      warmup_required: 21,
      warmup_complete: true,
      issues: [],
      bars: [],
      points: [],
      signal_status: "not_implemented",
      demark: {
        config: legacyConfig,
        input_hash: "td-input",
        history_start: at,
        history_end: at,
        history_status: "window_only",
        status: "ready",
        warmup_required: 6,
        sequences: [],
        events: [],
        qualified13_count: 0,
        issues: [],
      },
    },
  };

  it("reads a running v1 service without discarding its snapshot", async () => {
    const { getWorkspace } = await import("./client");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))),
    );
    const workspace = await getWorkspace(stream);
    expect(workspace.snapshot?.snapshot_id).toBe("legacy");
    expect(workspace.snapshot?.demark?.config.same_side_policy).toBe(
      "parallel",
    );
    expect(workspace.snapshot?.rules.demark?.same_side_policy).toBe("parallel");
  });

  it("does not invent a missing policy for a v2 result", async () => {
    const { getWorkspace } = await import("./client");
    const broken = JSON.parse(JSON.stringify(payload));
    broken.snapshot.demark.config.ruleset_version = "wheelhouse-sequential-2";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(broken))),
    );
    await expect(getWorkspace(stream)).rejects.toThrow("incompatible");
  });
});

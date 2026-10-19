import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getCostBasis,
  getOnchainCycle,
  getOnchainLevels,
  getPerpStates,
  getPerpStatus,
  getSellerPressure,
  getServiceStatus,
} from "./client";
import {
  costBasisSample,
  cycleSample,
  levelsSample,
  pressureSample,
} from "./onchain-contract";
import { perpStatesSample } from "./perps-contract";

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

describe("on-chain client", () => {
  it("reads the cycle and levels from the read-only on-chain endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string) =>
        Promise.resolve(
          new Response(
            JSON.stringify(url.endsWith("/cycle") ? cycleSample : levelsSample),
          ),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    expect((await getOnchainCycle()).state).toBe("breakout");
    expect((await getOnchainLevels()).lines).toHaveLength(5);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/wheelhouse/v1/onchain/cycle",
      "/api/wheelhouse/v1/onchain/levels",
    ]);
  });

  it("reads the seller pressure from the read-only endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(pressureSample())));
    vi.stubGlobal("fetch", fetchMock);
    const view = await getSellerPressure();
    expect(view.loss).toHaveLength(2200);
    expect(view.data_state).toBe("fresh");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/wheelhouse/v1/onchain/seller-pressure",
    ]);
  });

  it("rejects a seller pressure payload outside the contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ ...pressureSample(), data_state: "live" }),
          ),
        ),
    );
    await expect(getSellerPressure()).rejects.toThrow("incompatible");
  });

  it("reads the cost basis from the read-only endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(costBasisSample)));
    vi.stubGlobal("fetch", fetchMock);
    const view = await getCostBasis(new AbortController().signal);
    expect(view.data_state).toBe("fresh");
    expect(view.buckets.map((bucket) => bucket.bucket)).toEqual([
      200, 500, 1000,
    ]);
    expect(view.buckets[1].resistance).toEqual([86000, 88000, 96000, 104000]);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/wheelhouse/v1/onchain/cost-basis",
    ]);
  });

  it("rejects a cost basis payload outside the contract", async () => {
    const { buckets: _buckets, ...incomplete } = costBasisSample;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(incomplete))),
    );
    await expect(getCostBasis()).rejects.toThrow("incompatible");
  });

  it("reads a perp states view for the exchange and window asked", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(perpStatesSample())));
    vi.stubGlobal("fetch", fetchMock);
    const view = await getPerpStates(
      "bybit",
      "8h",
      new AbortController().signal,
    );
    expect(view.data_state).toBe("fresh");
    expect(view.blocks).toHaveLength(181);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/wheelhouse/v1/perps/states?exchange=bybit&window=8h",
    ]);
  });

  it("keeps a collecting perp view as served, with nothing judged", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify(perpStatesSample("collecting"))),
        ),
    );
    const view = await getPerpStates("all", "4h");
    expect(view.collecting).toBe(true);
    expect(view.blocks.every((block) => block.state === null)).toBe(true);
  });

  it("rejects a perp states payload outside the contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ ...perpStatesSample(), data_state: "live" }),
          ),
        ),
    );
    await expect(getPerpStates("all", "4h")).rejects.toThrow("incompatible");
  });

  it("surfaces a perp states failure instead of an empty view", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("Unavailable", { status: 503 })),
    );
    await expect(getPerpStates("all", "4h")).rejects.toThrow("HTTP 503");
  });

  it("reads the perps status from the read-only endpoint", async () => {
    const payload = {
      last_run_at: "2026-10-17T11:05:04Z",
      last_error: null,
      hosts: [
        {
          host: "fapi.binance.com",
          last_success: "2026-10-17T11:05:04Z",
          error: null,
          backoff_until: null,
        },
      ],
      collectors: (["binance_liq", "bybit_liq", "bybit_trades"] as const).map(
        (stream) => ({
          stream,
          live: true,
          last_proof: "2026-10-17T11:06:54Z",
          down_since: null,
          covered_days: 31.5,
          since: "2026-09-16T00:00:00Z",
          problems: {},
        }),
      ),
      markets: [],
      direction: "pending",
      direction_check: null,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(payload)));
    vi.stubGlobal("fetch", fetchMock);
    const status = await getPerpStatus(new AbortController().signal);
    expect(status.direction).toBe("pending");
    expect(status.collectors).toHaveLength(3);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/wheelhouse/v1/perps/status",
    ]);
  });

  it("hands the caller's abort signal to both perps requests", async () => {
    // Settles only when the signal fetch receives is aborted.
    const fetchMock = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) =>
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          ),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const states = new AbortController();
    const status = new AbortController();
    const pending = [
      getPerpStates("all", "4h", states.signal),
      getPerpStatus(status.signal),
    ];
    states.abort();
    status.abort();
    for (const request of pending)
      await expect(request).rejects.toThrow("did not respond");
    expect(
      fetchMock.mock.calls.map(([, init]) => init.signal?.aborted),
    ).toEqual([true, true]);
  });

  it("rejects a perps status payload outside the contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify({ last_run_at: null }))),
    );
    await expect(getPerpStatus()).rejects.toThrow("incompatible");
  });

  it("rejects an on-chain payload outside the contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ ...cycleSample, state: "bull" })),
        ),
    );
    await expect(getOnchainCycle()).rejects.toThrow("incompatible");
  });
});

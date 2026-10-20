import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getAgeCohorts,
  getCostBasis,
  getCostBasisHistory,
  getCostFlow,
  getOnchainCycle,
  getOnchainLevels,
  getPerpStates,
  getPerpStatus,
  getSellerPressure,
  getSellSide,
  getServiceStatus,
  getSizeCohorts,
} from "./client";
import historySample from "./cost-basis-history-sample.json";
import costFlowSample from "./cost-flow-sample.json";
import sellSideSample from "./sell-side-sample.json";
import sizeSample from "./size-cohorts-sample.json";
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

  it("reads the cost basis and the cost flow from the read-only endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              url.endsWith("/cost-flow") ? costFlowSample : costBasisSample,
            ),
          ),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const view = await getCostBasis(new AbortController().signal);
    expect(view.data_state).toBe("fresh");
    expect(view.buckets.map((bucket) => bucket.bucket)).toEqual([
      200, 500, 1000,
    ]);
    expect(view.buckets[1].resistance).toEqual([86000, 88000, 96000, 104000]);
    const flow = await getCostFlow(new AbortController().signal);
    expect(flow.now_day).toBe("2026-10-19");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/wheelhouse/v1/onchain/cost-basis",
      "/api/wheelhouse/v1/onchain/cost-flow",
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

  it("reads the cost-basis history by span, with longer timeouts for the long spans", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string) =>
        Promise.resolve(
          new Response(
            JSON.stringify(
              url.endsWith("/sell-side") ? sellSideSample : historySample,
            ),
          ),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    try {
      const view = await getCostBasisHistory("all", new AbortController().signal);
      expect(view.days).toHaveLength(30);
      await getCostBasisHistory("365");
      await getSellSide();
      expect(timeout.mock.calls).toEqual([[30_000], [15_000], [5000]]);
      expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
        "/api/wheelhouse/v1/onchain/cost-basis-history?span=all",
        "/api/wheelhouse/v1/onchain/cost-basis-history?span=365",
        "/api/wheelhouse/v1/onchain/sell-side",
      ]);
    } finally {
      timeout.mockRestore();
    }
  });

  it("hands the caller's abort signal to the cost-basis history request", async () => {
    const fetchMock = vi.fn(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) =>
          init.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          ),
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const pending = getCostBasisHistory("90", controller.signal);
    controller.abort();
    await expect(pending).rejects.toThrow("did not respond");
    expect(fetchMock.mock.calls[0][1].signal?.aborted).toBe(true);
  });

  it("says the service did not respond when the timeout cuts off a long body", async () => {
    const timer = new AbortController();
    const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(timer.signal);
    // The headers arrive at once; the body stops part way and fails when the request is aborted.
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new TextEncoder().encode('{"data_state":'));
            init.signal?.addEventListener("abort", () =>
              controller.error(init.signal?.reason),
            );
          },
        });
        return Promise.resolve(new Response(body));
      }),
    );
    try {
      const pending = getCostBasisHistory("all");
      timer.abort(new DOMException("signal timed out", "TimeoutError"));
      await expect(pending).rejects.toThrow(
        "Python service did not respond. Check the local workspace and retry.",
      );
    } finally {
      timeout.mockRestore();
    }
  });

  it("keeps a malformed body's own error on the on-chain endpoints", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => Promise.resolve(new Response("{not json"))),
    );
    for (const request of [
      () => getCostBasisHistory("30"),
      () => getCostBasisHistory("all"),
      () => getSellSide(),
      () => getAgeCohorts(),
      () => getCostFlow(),
      () => getCostBasis(),
      () => getSizeCohorts(),
      () => getSellerPressure(),
      () => getOnchainCycle(),
      () => getOnchainLevels(),
    ])
      await expect(request()).rejects.toThrow(SyntaxError);
  });

  it("rejects a cost-basis history payload outside the contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ ...historySample, close: historySample.close.slice(1) }),
          ),
        ),
    );
    await expect(getCostBasisHistory("30")).rejects.toThrow("incompatible");
  });

  it("reads the size cohorts from the read-only endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(sizeSample)));
    vi.stubGlobal("fetch", fetchMock);
    const view = await getSizeCohorts(new AbortController().signal);
    expect(view.bands.map((band) => band.band)[11]).toBe("addrs_over_100k_btc");
    expect(view.last_at).toBe("2026-10-19T06:00:00Z");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/wheelhouse/v1/onchain/size-cohorts",
    ]);
  });

  it("rejects a size-cohort payload outside the contract", async () => {
    const reversed = { ...sizeSample, bands: [...sizeSample.bands].reverse() };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(reversed))),
    );
    await expect(getSizeCohorts()).rejects.toThrow("incompatible");
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

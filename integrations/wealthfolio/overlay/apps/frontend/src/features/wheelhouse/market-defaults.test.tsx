import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import MarketPage from "./market-page";
import { cycleSample, levelsSample } from "./onchain-contract";
const mocks = vi.hoisted(() => ({
  workspace: vi.fn(),
  submit: vi.fn(),
  snapshot: vi.fn(),
  levels: vi.fn(),
  cycle: vi.fn(),
  chart: vi.fn(),
}));
// Records the props the page gives the chart, so overlays can be asserted without drawing.
vi.mock("./market-chart", () => ({
  MarketChart: (props: unknown) => {
    mocks.chart(props);
    return null;
  },
}));
vi.mock("./demark-details", () => ({ DemarkDetails: () => null }));
vi.mock("./regime-check", () => ({ RegimeCheck: () => null }));
vi.mock("./language-toggle", () => ({ LanguageToggle: () => null }));
vi.mock("./i18n", () => ({
  useWheelhouseText: () => ({ text: (key: string) => key }),
  labeled: (_: unknown, _kind: string, value: string) => value,
  issueText: () => "",
  messages: { en: {}, zh: {} },
}));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getServiceStatus: async () => ({ service_version: "test" }),
  getWorkspace: mocks.workspace,
  getSnapshots: async () => [],
  getSnapshot: mocks.snapshot,
  getJobEvents: async () => [],
  submitJob: mocks.submit,
  getOnchainLevels: mocks.levels,
  getOnchainCycle: mocks.cycle,
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it.each([
  ["BTCUSDT", "bybit", "bybit-spot", "BTC"],
  ["ETHUSDT", "binance", "binance-usdm-perpetual", "ETH"],
  ["MUUSDT", "binance", "binance-usdm-perpetual", "MU"],
])(
  "routes %s to its assigned market even with a legacy fixture URL",
  async (symbol, source, venue, currency) => {
    mocks.workspace.mockResolvedValue({
      snapshot: null,
      latest_job: null,
      refresh_job: null,
      schedule: null,
      current_state: "unavailable",
    });
    mocks.submit.mockImplementation(() => new Promise(() => {}));
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter
          initialEntries={[
            `/market-intelligence?source=fixture&symbol=${symbol}`,
          ]}
        >
          <MarketPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    expect(mocks.submit.mock.calls[0][0].stream).toMatchObject({
      source,
      symbol,
      venue,
      base_currency: currency,
    });
    expect(
      screen
        .getByRole("tab", { name: /method\.td/ })
        .getAttribute("aria-selected"),
    ).toBe("true");
    expect(screen.queryByLabelText("field.source")).toBeNull();
    expect(screen.queryByRole("button", { name: "action.refresh" })).toBeNull();
    expect(screen.queryByRole("button", { name: "chart.load" })).toBeNull();
  },
);

// The chart only renders for a dataset that matches the selected stream.
const snapshotFor = (symbol: string) => ({
  snapshot_id: "a".repeat(64),
  input_hash: "h".repeat(64),
  mode: "retrospective",
  stream: {
    source: symbol === "BTCUSDT" ? "bybit" : "binance",
    venue: symbol === "BTCUSDT" ? "bybit-spot" : "binance-usdm-perpetual",
    symbol,
    timeframe: "1h",
  },
  rules: { engine_version: "baseline-v1", window: 20, demark: null },
  bars: [],
  points: [],
  issues: [],
  warmup_complete: true,
  warmup_required: 21,
  closed_bar_time: null,
  demark: null,
});

function openLevels(
  search: string,
  { symbol = "BTCUSDT", levels = levelsSample as unknown } = {},
) {
  mocks.workspace.mockResolvedValue({
    snapshot: snapshotFor(symbol),
    latest_job: null,
    refresh_job: null,
    schedule: null,
    current_state: "fresh",
  });
  mocks.snapshot.mockResolvedValue(snapshotFor(symbol));
  if (levels instanceof Error) mocks.levels.mockRejectedValue(levels);
  else mocks.levels.mockResolvedValue(levels);
  mocks.cycle.mockResolvedValue(cycleSample);
  mocks.submit.mockImplementation(() => new Promise(() => {}));
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={[`/market-intelligence${search}`]}>
        <MarketPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
type Overlay = { id: string; label: string; price: number };
const lastOverlays = () =>
  (mocks.chart.mock.calls.at(-1)?.[0] as { overlays?: Overlay[] } | undefined)
    ?.overlays;

it("passes the five on-chain model lines to the BTC live Key levels chart", async () => {
  openLevels("?symbol=BTCUSDT&method=levels");
  await waitFor(() => expect(lastOverlays()).toHaveLength(5));
  expect(lastOverlays()).toEqual(
    levelsSample.lines.map((line) => ({
      id: line.name,
      label: `levels.line.${line.name}`,
      price: line.price,
    })),
  );
  expect(screen.queryByText("levels.btcOnly")).toBeNull();
  expect(screen.queryByText("levels.latestOnly")).toBeNull();
});

it("marks stale model lines in their chart labels", async () => {
  openLevels("?symbol=BTCUSDT&method=levels", {
    levels: { ...levelsSample, data_state: "stale" },
  });
  await waitFor(() => expect(lastOverlays()).toHaveLength(5));
  expect(lastOverlays()?.every((o) => o.label === "levels.overlayStale")).toBe(
    true,
  );
});

it("draws no overlays when the on-chain request fails", async () => {
  openLevels("?symbol=BTCUSDT&method=levels", { levels: new Error("down") });
  expect(await screen.findByText("levels.unavailable")).toBeTruthy();
  await waitFor(() => expect(mocks.chart).toHaveBeenCalled());
  expect(lastOverlays() ?? []).toHaveLength(0);
});

it("draws no overlays for unavailable on-chain data", async () => {
  openLevels("?symbol=BTCUSDT&method=levels", {
    levels: {
      ...levelsSample,
      data_state: "unavailable",
      reasons: ["brk_unavailable"],
      lines: [],
      as_of: null,
      brk_version: null,
      forming_at: null,
    },
  });
  expect(await screen.findByText("levels.unavailable")).toBeTruthy();
  await waitFor(() => expect(mocks.chart).toHaveBeenCalled());
  expect(lastOverlays() ?? []).toHaveLength(0);
});

it("gives ETH no overlays and says on-chain lines are BTC only", async () => {
  openLevels("?symbol=ETHUSDT&method=levels", { symbol: "ETHUSDT" });
  expect(await screen.findByText("levels.btcOnly")).toBeTruthy();
  await waitFor(() => expect(mocks.chart).toHaveBeenCalled());
  expect(lastOverlays() ?? []).toHaveLength(0);
  expect(mocks.levels).not.toHaveBeenCalled();
});

it("gives a selected snapshot no overlays and says the lines are latest-only", async () => {
  openLevels(`?symbol=BTCUSDT&method=levels&snapshot=${"a".repeat(64)}`);
  expect(await screen.findByText("levels.latestOnly")).toBeTruthy();
  await waitFor(() => expect(mocks.chart).toHaveBeenCalled());
  expect(mocks.snapshot).toHaveBeenCalled();
  expect(lastOverlays() ?? []).toHaveLength(0);
  expect(mocks.levels).not.toHaveBeenCalled();
});

it("gives the TD Sequential tab no overlays", async () => {
  openLevels("?symbol=BTCUSDT&method=td");
  await waitFor(() => expect(mocks.chart).toHaveBeenCalled());
  expect(lastOverlays() ?? []).toHaveLength(0);
  expect(mocks.levels).not.toHaveBeenCalled();
});

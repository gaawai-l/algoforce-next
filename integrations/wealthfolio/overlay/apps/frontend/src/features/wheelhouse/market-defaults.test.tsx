import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import MarketPage from "./market-page";
import { costBasisSample, cycleSample, levelsSample } from "./onchain-contract";
const mocks = vi.hoisted(() => ({
  workspace: vi.fn(),
  submit: vi.fn(),
  snapshot: vi.fn(),
  levels: vi.fn(),
  cycle: vi.fn(),
  costBasis: vi.fn(),
  chart: vi.fn(),
  text: vi.fn((key: string) => key),
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
// The seller charts have their own tests; here only whether the page mounts them matters.
vi.mock("./seller-charts", () => ({
  SellerCharts: () => <p>seller-charts</p>,
}));
vi.mock("./language-toggle", () => ({ LanguageToggle: () => null }));
vi.mock("./i18n", () => ({
  useWheelhouseText: () => ({ text: mocks.text }),
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
  getCostBasis: mocks.costBasis,
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
  {
    symbol = "BTCUSDT",
    levels = levelsSample as unknown,
    costBasis = costBasisSample as unknown,
  } = {},
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
  if (costBasis === "pending")
    mocks.costBasis.mockImplementation(() => new Promise(() => {}));
  else if (costBasis instanceof Error)
    mocks.costBasis.mockRejectedValue(costBasis);
  else mocks.costBasis.mockResolvedValue(costBasis);
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
type Band = { id: string; cohort: string; price: number };
const lastProps = () =>
  mocks.chart.mock.calls.at(-1)?.[0] as
    | { overlays?: Overlay[]; rail?: Band[] }
    | undefined;
const lastOverlays = () => lastProps()?.overlays;
const lastRail = () => lastProps()?.rail;

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

it("marks the median chart label with its date when URPD is older than the as-of day", async () => {
  openLevels("?symbol=BTCUSDT&method=levels", {
    levels: { ...levelsSample, urpd_date: "2026-10-15" },
  });
  await waitFor(() => expect(lastOverlays()).toHaveLength(5));
  expect(lastOverlays()?.map((o) => [o.id, o.label])).toEqual([
    ["true_mean", "levels.line.true_mean"],
    ["short_term", "levels.line.short_term"],
    ["average", "levels.line.average"],
    ["long_term", "levels.line.long_term"],
    ["median", "levels.line.medianUrpd"],
  ]);
  // The date is the URPD day, written as a short day, e.g. "15 Oct".
  expect(mocks.text).toHaveBeenCalledWith("cycle.date", {
    day: 15,
    month: "Oct",
  });
  expect(mocks.text).toHaveBeenCalledWith("levels.line.medianUrpd", {
    date: "cycle.date",
  });
});

it("marks a stale median chart label with both its date and the stale note", async () => {
  openLevels("?symbol=BTCUSDT&method=levels", {
    levels: { ...levelsSample, data_state: "stale", urpd_date: "2026-10-15" },
  });
  await waitFor(() => expect(lastOverlays()).toHaveLength(5));
  expect(lastOverlays()?.every((o) => o.label === "levels.overlayStale")).toBe(
    true,
  );
  expect(mocks.text).toHaveBeenCalledWith("levels.overlayStale", {
    name: "levels.line.medianUrpd",
  });
  expect(mocks.text).toHaveBeenCalledWith("levels.overlayStale", {
    name: "levels.line.average",
  });
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

it("lists four method tabs and ends with Flows", async () => {
  openLevels("?symbol=BTCUSDT&method=td");
  const tabs = await screen.findAllByRole("tab");
  expect(tabs.map((tab) => tab.textContent)).toEqual([
    "01method.td",
    "02method.levels",
    "03method.fib",
    "04method.flows",
  ]);
});

it("moves focus from Fibonacci to Flows with the right arrow key", async () => {
  openLevels("?symbol=BTCUSDT&method=fib");
  const fib = await screen.findByRole("tab", { name: /method\.fib/ });
  fib.focus();
  fireEvent.keyDown(fib, { key: "ArrowRight" });
  const flows = screen.getByRole("tab", { name: /method\.flows/ });
  expect(document.activeElement).toBe(flows);
  await waitFor(() => expect(flows.getAttribute("aria-selected")).toBe("true"));
});

it("wraps from Flows to TD Sequential and End jumps to Flows", async () => {
  openLevels("?symbol=BTCUSDT&method=flows");
  const flows = await screen.findByRole("tab", { name: /method\.flows/ });
  fireEvent.keyDown(flows, { key: "ArrowRight" });
  const td = screen.getByRole("tab", { name: /method\.td/ });
  expect(document.activeElement).toBe(td);
  fireEvent.keyDown(td, { key: "End" });
  expect(document.activeElement).toBe(
    screen.getByRole("tab", { name: /method\.flows/ }),
  );
});

// Resolves once the workspace response has rendered (the frame badge shows its
// state), so absence checks cannot pass just because nothing has loaded yet.
async function settled() {
  await waitFor(() => expect(mocks.workspace).toHaveBeenCalled());
  expect(await screen.findByText("fresh")).toBeTruthy();
}

it("shows the Flows panel without timeframe controls or a chart", async () => {
  openLevels("?symbol=BTCUSDT&method=flows");
  expect(await screen.findByText("seller-charts")).toBeTruthy();
  await settled();
  expect(
    screen
      .getByRole("tab", { name: /method\.flows/ })
      .getAttribute("aria-selected"),
  ).toBe("true");
  expect(screen.queryByRole("group", { name: "timeframe.group" })).toBeNull();
  expect(screen.queryByRole("button", { name: "5M" })).toBeNull();
  expect(screen.queryByLabelText("visibleBars")).toBeNull();
  expect(mocks.chart).not.toHaveBeenCalled();
  expect(mocks.levels).not.toHaveBeenCalled();
});

it("reaches the perp placeholder from flow=perp", async () => {
  openLevels("?symbol=BTCUSDT&method=flows&flow=perp");
  expect(await screen.findByText("flows.perpPending")).toBeTruthy();
  expect(screen.queryByText("seller-charts")).toBeNull();
  await settled();
  expect(mocks.chart).not.toHaveBeenCalled();
});

it("hides the K-line replay, audit and OHLC sections under Flows", async () => {
  openLevels("?symbol=BTCUSDT&method=flows");
  expect(await screen.findByText("seller-charts")).toBeTruthy();
  await settled();
  expect(screen.queryByText("replay.title")).toBeNull();
  expect(screen.queryByText("audit.summary")).toBeNull();
  expect(screen.queryByText("ohlc.summary")).toBeNull();
  expect(screen.getByText("price.label")).toBeTruthy();
});

it("shows the K-line replay, audit and OHLC sections under Key levels", async () => {
  openLevels("?symbol=BTCUSDT&method=levels");
  expect(await screen.findByText("replay.title")).toBeTruthy();
  expect(screen.getByText("audit.summary")).toBeTruthy();
  expect(await screen.findByText("ohlc.summary")).toBeTruthy();
});

it("keeps the timeframe controls on the other tabs", async () => {
  openLevels("?symbol=BTCUSDT&method=td");
  expect(
    await screen.findByRole("group", { name: "timeframe.group" }),
  ).toBeTruthy();
});

it("says flows are BTC only for ETH while the tab stays selectable", async () => {
  openLevels("?symbol=ETHUSDT&method=flows", { symbol: "ETHUSDT" });
  expect(await screen.findByText("flows.btcOnly")).toBeTruthy();
  await settled();
  expect(mocks.chart).not.toHaveBeenCalled();
  expect(screen.queryByText("seller-charts")).toBeNull();
  expect(
    screen
      .getByRole("tab", { name: /method\.flows/ })
      .getAttribute("aria-selected"),
  ).toBe("true");
});

const toggle = (name: string) => screen.getByRole("button", { name });
const pressed = (name: string) => toggle(name).getAttribute("aria-pressed");
const resistance = () =>
  screen.getByRole("row", { name: /costBasis\.resistance/ }).textContent;

it("shows the Key levels controls with every layer on and the $500 bucket", async () => {
  openLevels("?symbol=BTCUSDT&method=levels");
  expect(
    await screen.findByRole("group", { name: "costBasis.layers" }),
  ).toBeTruthy();
  expect(pressed("costBasis.lines")).toBe("true");
  expect(pressed("costBasis.sth")).toBe("true");
  expect(pressed("costBasis.lth")).toBe("true");
  expect(
    screen.getByRole("group", { name: "costBasis.bucket" }).textContent,
  ).toBe("$200$500$1000");
  expect(pressed("$500")).toBe("true");
  expect(pressed("$200")).toBe("false");
  // The rail carries both cohorts' $500 peaks.
  await waitFor(() => expect(lastRail()).toHaveLength(7));
  expect(lastRail()?.map((b) => b.price)).toEqual([
    ...costBasisSample.buckets[1].sth.peaks.map((p) => p.price),
    ...costBasisSample.buckets[1].lth.peaks.map((p) => p.price),
  ]);
  // Each band toggle has its legend: total, floor and share in profit.
  expect(mocks.text).toHaveBeenCalledWith("costBasis.legend", {
    btc: "3.66M",
    floor: "$1k",
    profit: "62%",
  });
});

it("hides the cost lines without touching the levels table", async () => {
  openLevels("?symbol=BTCUSDT&method=levels");
  await waitFor(() => expect(lastOverlays()).toHaveLength(5));
  const before = resistance();
  expect(before).toContain("$86.0k");
  fireEvent.click(toggle("costBasis.lines"));
  expect(pressed("costBasis.lines")).toBe("false");
  expect(lastOverlays() ?? []).toHaveLength(0);
  expect(resistance()).toBe(before);
  expect(lastRail()).toHaveLength(7);
});

it("drops the STH bands from the rail when they are switched off", async () => {
  openLevels("?symbol=BTCUSDT&method=levels");
  await waitFor(() => expect(lastRail()).toHaveLength(7));
  fireEvent.click(toggle("costBasis.sth"));
  expect(lastRail()?.some((b) => b.cohort === "sth")).toBe(false);
  expect(lastRail()).toHaveLength(5);
  fireEvent.click(toggle("costBasis.lth"));
  expect(lastRail()).toEqual([]);
});

it("switches the bucket without asking for cost basis again", async () => {
  openLevels("?symbol=BTCUSDT&method=levels");
  await waitFor(() => expect(lastRail()).toHaveLength(7));
  expect(mocks.costBasis).toHaveBeenCalledTimes(1);
  fireEvent.click(toggle("$1000"));
  expect(pressed("$1000")).toBe("true");
  expect(lastRail()?.map((b) => b.price)).toEqual([
    ...costBasisSample.buckets[2].sth.peaks.map((p) => p.price),
    ...costBasisSample.buckets[2].lth.peaks.map((p) => p.price),
  ]);
  expect(resistance()).toContain("$90.0k");
  expect(mocks.costBasis).toHaveBeenCalledTimes(1);
});

it("keeps room for the rail and the band legend before the cost basis arrives", async () => {
  openLevels("?symbol=BTCUSDT&method=levels", { costBasis: "pending" });
  await waitFor(() => expect(mocks.chart).toHaveBeenCalled());
  expect(lastRail()).toEqual([]);
  expect(mocks.costBasis).toHaveBeenCalled();
  // The legend row is there with placeholders, so the chart does not move when data arrives.
  expect(document.querySelector(".wh-cb-legend")?.textContent).toBe(
    "costBasis.sth · —costBasis.lth · —",
  );
});

it("gives a failed cost-basis request an empty rail", async () => {
  openLevels("?symbol=BTCUSDT&method=levels", {
    costBasis: new Error("down"),
  });
  expect(await screen.findByText("costBasis.unavailable")).toBeTruthy();
  expect(lastRail()).toEqual([]);
});

it.each([
  ["ETH", "?symbol=ETHUSDT&method=levels", "ETHUSDT"],
  [
    "a saved snapshot",
    `?symbol=BTCUSDT&method=levels&snapshot=${"a".repeat(64)}`,
    "BTCUSDT",
  ],
])("gives %s no Key levels controls and no rail", async (_, search, symbol) => {
  openLevels(search, { symbol });
  await waitFor(() => expect(mocks.chart).toHaveBeenCalled());
  expect(screen.queryByRole("group", { name: "costBasis.layers" })).toBeNull();
  expect(screen.queryByRole("group", { name: "costBasis.bucket" })).toBeNull();
  expect(lastRail()).toBeUndefined();
  expect(mocks.costBasis).not.toHaveBeenCalled();
});

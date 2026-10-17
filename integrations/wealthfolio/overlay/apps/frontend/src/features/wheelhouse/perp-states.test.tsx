import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { messages } from "./i18n";
import { PerpStates } from "./perp-states";
import {
  perpStatesSample,
  type PerpStatesView,
  type PerpsStatus,
} from "./perps-contract";

const mocks = vi.hoisted(() => ({ states: vi.fn(), status: vi.fn() }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getPerpStates: mocks.states,
  getPerpStatus: mocks.status,
}));

// The shared test setup mocks matchMedia as a narrow screen; each test sets its own width.
function viewport(wide: boolean) {
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({
        matches: wide,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}

beforeEach(() => viewport(true));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const tableTitle = "Table 1 — Perp states";
const header =
  "Resolution 10m · Data through 2026-10-17 11:00 UTC · Price Bybit spot · OI/flows Binance USDⓈ-M + Bybit linear (public) · liquidations collected since 2026-09-16";
const binanceNote =
  "Binance liquidations are a one-per-second snapshot (lower bound)";

function status(direction: PerpsStatus["direction"]): PerpsStatus {
  return {
    last_run_at: "2026-10-17T11:05:04Z",
    last_error: null,
    hosts: [],
    collectors: [],
    direction,
    direction_check: null,
  };
}

function Where() {
  return <output data-testid="where">{useLocation().search}</output>;
}

function show({
  view = perpStatesSample(),
  direction = "ok",
  search = "",
  cached,
  cachedDirection,
}: {
  view?: PerpStatesView | Error | "pending";
  direction?: PerpsStatus["direction"] | Error;
  search?: string;
  // An earlier successful reading of the default view, which a failed refetch leaves cached.
  cached?: PerpStatesView;
  // An earlier status verdict, kept in the cache when the status refetch fails.
  cachedDirection?: PerpsStatus["direction"];
} = {}) {
  if (view === "pending") mocks.states.mockReturnValue(new Promise(() => {}));
  else if (view instanceof Error) mocks.states.mockRejectedValue(view);
  else mocks.states.mockResolvedValue(view);
  if (direction instanceof Error) mocks.status.mockRejectedValue(direction);
  else mocks.status.mockResolvedValue(status(direction));
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // The status is known from the first frame, so labels never flicker in an assertion; the
  // component still refetches it on mount.
  if (!(direction instanceof Error))
    client.setQueryData(["wh", "perps", "status"], status(direction));
  if (cached) client.setQueryData(["wh", "perps", "all", "4h"], cached);
  if (cachedDirection)
    client.setQueryData(["wh", "perps", "status"], status(cachedDirection));
  const rendered = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/market-intelligence${search}`]}>
        <PerpStates />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...rendered };
}

const where = () =>
  new URLSearchParams(screen.getByTestId("where").textContent ?? "");
const table = () => screen.getByRole("table");
const bodyRows = () => within(table()).getAllByRole("row").slice(1);
const columns = () =>
  within(table())
    .getAllByRole("columnheader")
    .map((cell) => cell.textContent);
const cellsOf = (row: HTMLElement) =>
  [...row.querySelectorAll("th, td")].map((cell) => cell.textContent ?? "");
const pressed = (name: string) =>
  screen.getByRole("button", { name }).getAttribute("aria-pressed");
const subtitle = () =>
  document.querySelector(".wh-perp-subtitle")?.textContent ?? "";

it("shows Table 1 with the eight states in order and shares adding up to 100", async () => {
  show();
  expect(await screen.findByText(tableTitle)).toBeTruthy();
  expect(columns()).toEqual([
    "State",
    "What it is",
    "Prob. [30d]",
    "Max move / duration",
  ]);
  const rows = bodyRows();
  expect(rows).toHaveLength(8);
  expect(rows.map((row) => row.getAttribute("data-state"))).toEqual([
    "shortsq",
    "longsq",
    "shortun",
    "longun",
    "longbd",
    "shortbd",
    "spot",
    "chop",
  ]);
  const shares = rows.map((row) => cellsOf(row)[2]);
  expect(shares).toEqual(["4%", "5%", "7%", "5%", "5%", "5%", "17%", "52%"]);
  expect(shares.reduce((sum, share) => sum + Number.parseInt(share), 0)).toBe(
    100,
  );
  expect(cellsOf(rows[0])[0]).toBe("Short squeeze");
  expect(cellsOf(rows[0])[1]).toBe("Shorts forced to buy back");
  expect(cellsOf(rows[0])[3]).toBe("+2.89% · 4h");
  expect(cellsOf(rows[6])[3]).toBe("−2.90% · 12h");
  expect(cellsOf(rows[7])[3]).toBe("−1.83% · 20h");
  expect(subtitle()).toBe(
    "180 judged of 180 blocks in view · share of blocks, not a forecast",
  );
  expect(document.querySelectorAll("details")).toHaveLength(0);
});

it("shows the header line, the coverage of each stream and the Binance note", async () => {
  show();
  expect(await screen.findByText(header)).toBeTruthy();
  expect(
    screen.getByText(
      "Collected in the last 90 days: Binance liquidations 31.5 d · Bybit liquidations 31.5 d · Bybit trades 31.5 d",
    ),
  ).toBeTruthy();
  expect(screen.getByText(binanceNote)).toBeTruthy();
  expect(document.querySelectorAll(".wh-onchain-warn")).toHaveLength(0);
});

it("leaves out the Binance note and other streams on the Bybit view", async () => {
  const view = perpStatesSample();
  view.exchange = "bybit";
  view.collectors = view.collectors.filter(
    (collector) => collector.stream !== "binance_liq",
  );
  show({ view, search: "?px=bybit" });
  expect(
    await screen.findByText(
      "Collected in the last 90 days: Bybit liquidations 31.5 d · Bybit trades 31.5 d",
    ),
  ).toBeTruthy();
  expect(screen.queryByText(binanceNote)).toBeNull();
});

it("dates the liquidations from the later of the view's liquidation streams", async () => {
  const view = perpStatesSample();
  view.collectors[1].since = "2026-09-20T06:00:00Z";
  view.collectors[2].since = "2026-09-25T06:00:00Z";
  show({ view });
  expect(
    await screen.findByText(/liquidations collected since 2026-09-20$/),
  ).toBeTruthy();
});

it("marks the latest block in the row of its state and says it is forming", async () => {
  show();
  const marker = await screen.findByRole("img", {
    name: "Latest block (forming)",
  });
  expect(marker.closest("tr")?.getAttribute("data-state")).toBe("chop");
  expect(screen.getAllByRole("img", { name: /Latest block/ })).toHaveLength(1);
  expect(
    screen.getByText(
      "The latest block was still forming when computed (18 of 24 ten-minute buckets); its state can change.",
    ),
  ).toBeTruthy();
});

it("marks no row when the latest block is uncovered, and names the downed collectors", async () => {
  show({ view: perpStatesSample("uncovered") });
  await screen.findByText(tableTitle);
  expect(screen.queryByRole("img", { name: /Latest block/ })).toBeNull();
  expect(subtitle()).toBe(
    "179 judged of 180 blocks in view · share of blocks, not a forecast · latest block uncovered",
  );
  expect(
    screen.getByText(
      "Binance liquidations collector down since 2026-10-17 09:30 UTC · Bybit liquidations collector down since 2026-10-17 09:30 UTC · Bybit trades collector down since 2026-10-17 09:30 UTC",
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/collector_down/)).toBeNull();
});

it("says a collector that never connected has not connected yet", async () => {
  const view = perpStatesSample();
  view.collectors[2] = {
    ...view.collectors[2],
    live: false,
    last_proof: null,
    down_since: null,
    covered_days: 0,
    since: null,
  };
  view.reasons = ["collector_down:bybit_trades"];
  show({ view });
  expect(
    await screen.findByText("Bybit trades collector has not connected yet"),
  ).toBeTruthy();
});

it("shows the collecting banner instead of Table 1, keeping the parameters", async () => {
  show({ view: perpStatesSample("collecting") });
  expect(
    await screen.findByText(
      "Collecting liquidations (and Bybit trades) · 3.5 of 7 days (target 90)",
    ),
  ).toBeTruthy();
  expect(screen.queryByText(tableTitle)).toBeNull();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByText(/collecting:/)).toBeNull();
  expect(screen.getByRole("button", { name: "All venues" })).toBeTruthy();
  expect(
    screen.getByText(header.replace("2026-09-16", "2026-10-14")),
  ).toBeTruthy();
});

it("leaves Bybit trades out of the collecting banner on the Binance view", async () => {
  const view = perpStatesSample("collecting");
  view.exchange = "binance";
  view.collectors = view.collectors.filter(
    (collector) => collector.stream === "binance_liq",
  );
  show({ view, search: "?px=binance" });
  expect(
    await screen.findByText(
      "Collecting liquidations · 3.5 of 7 days (target 90)",
    ),
  ).toBeTruthy();
});

it("tags the squeezes until the liquidation direction is verified", async () => {
  show({ direction: "pending" });
  await screen.findByText(tableTitle);
  await waitFor(() => expect(mocks.status).toHaveBeenCalledOnce());
  const labels = () => bodyRows().map((row) => cellsOf(row)[0]);
  expect(labels().slice(0, 3)).toEqual([
    "Short squeeze (direction unverified)",
    "Long squeeze (direction unverified)",
    "Short unwind",
  ]);
  expect(labels().filter((label) => label.includes("unverified"))).toHaveLength(
    2,
  );
});

it("drops the tag once the direction is ok", async () => {
  show({ direction: "ok" });
  await screen.findByText(tableTitle);
  await waitFor(() => expect(cellsOf(bodyRows()[0])[0]).toBe("Short squeeze"));
  expect(screen.queryByText(/unverified/)).toBeNull();
});

it("keeps the tag when the direction is inverted or the status fails", async () => {
  show({ direction: "inverted" });
  await screen.findByText(tableTitle);
  await waitFor(() => expect(mocks.status).toHaveBeenCalledOnce());
  expect(cellsOf(bodyRows()[1])[0]).toBe("Long squeeze (direction unverified)");
  cleanup();
  show({ direction: new Error("status down") });
  await screen.findByText(tableTitle);
  expect(cellsOf(bodyRows()[0])[0]).toBe(
    "Short squeeze (direction unverified)",
  );
});

it("does not trust an older ok once the status request fails", async () => {
  show({ direction: new Error("status down"), cachedDirection: "ok" });
  await screen.findByText(tableTitle);
  await waitFor(() =>
    expect(cellsOf(bodyRows()[0])[0]).toBe(
      "Short squeeze (direction unverified)",
    ),
  );
});

it("defaults to all venues, 4h and 30d, and asks for that view", async () => {
  show();
  await screen.findByText(tableTitle);
  expect(pressed("All venues")).toBe("true");
  expect(pressed("4h")).toBe("true");
  expect(pressed("30d")).toBe("true");
  expect(mocks.states).toHaveBeenCalledWith(
    "all",
    "4h",
    expect.any(AbortSignal),
  );
});

it("falls back to the defaults for values outside the parameters", async () => {
  show({ search: "?px=okx&pw=1h&ps=90" });
  await screen.findByText(tableTitle);
  expect(pressed("All venues")).toBe("true");
  expect(pressed("4h")).toBe("true");
  expect(pressed("30d")).toBe("true");
  expect(mocks.states.mock.calls.map(([px, pw]) => [px, pw])).toEqual([
    ["all", "4h"],
  ]);
});

it("reads the parameters from the URL", async () => {
  show({ search: "?px=bybit&pw=8h&ps=7" });
  await screen.findByText(tableTitle);
  expect(pressed("Bybit")).toBe("true");
  expect(pressed("8h")).toBe("true");
  expect(pressed("7d")).toBe("true");
  expect(mocks.states).toHaveBeenCalledWith(
    "bybit",
    "8h",
    expect.any(AbortSignal),
  );
  expect(columns()[2]).toBe("Prob. [7d]");
});

it("writes each parameter to the URL and keeps the other parameters", async () => {
  show({ search: "?symbol=BTCUSDT&method=flows&flow=perp" });
  await screen.findByText(tableTitle);
  fireEvent.click(screen.getByRole("button", { name: "Binance" }));
  expect(where().get("px")).toBe("binance");
  await waitFor(() =>
    expect(mocks.states).toHaveBeenLastCalledWith(
      "binance",
      "4h",
      expect.any(AbortSignal),
    ),
  );
  fireEvent.click(screen.getByRole("button", { name: "8h" }));
  expect(where().get("pw")).toBe("8h");
  await waitFor(() =>
    expect(mocks.states).toHaveBeenLastCalledWith(
      "binance",
      "8h",
      expect.any(AbortSignal),
    ),
  );
  await screen.findByText(tableTitle);
  fireEvent.click(screen.getByRole("button", { name: "7d" }));
  expect(where().get("ps")).toBe("7");
  for (const [name, value] of [
    ["symbol", "BTCUSDT"],
    ["method", "flows"],
    ["flow", "perp"],
  ])
    expect(where().get(name)).toBe(value);
});

it("switches Show from the loaded view without another request", async () => {
  show();
  await screen.findByText(tableTitle);
  await waitFor(() => expect(mocks.status).toHaveBeenCalledOnce());
  fireEvent.click(screen.getByRole("button", { name: "7d" }));
  expect(pressed("7d")).toBe("true");
  expect(subtitle()).toBe(
    "42 judged of 42 blocks in view · share of blocks, not a forecast",
  );
  expect(columns()[2]).toBe("Prob. [7d]");
  expect(cellsOf(bodyRows()[6])[2]).toBe("14%");
  expect(cellsOf(bodyRows()[6])[3]).toBe("+2.77% · 4h");
  fireEvent.click(screen.getByRole("button", { name: "30d" }));
  expect(subtitle()).toMatch(/^180 judged of 180/);
  expect(mocks.states).toHaveBeenCalledOnce();
  expect(mocks.status).toHaveBeenCalledOnce();
});

it("shows a loading line and the parameters while the view loads", () => {
  show({ view: "pending" });
  expect(screen.getByText("Loading perp states…")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Bybit" })).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
});

it("says the view is unavailable when the request fails, whatever was cached", async () => {
  const { client } = show({
    view: new Error("Python service unavailable (HTTP 503)."),
    cached: perpStatesSample(),
  });
  expect(await screen.findByText("Perp states unavailable")).toBeTruthy();
  expect(
    screen.getByText("Python service unavailable (HTTP 503)."),
  ).toBeTruthy();
  // The older reading is still cached, yet nothing of it is shown.
  expect(client.getQueryData(["wh", "perps", "all", "4h"])).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByText(/Resolution 10m/)).toBeNull();
  expect(screen.getByRole("button", { name: "Binance" })).toBeTruthy();
});

it("shows an unavailable view with its reasons and no table", async () => {
  const view: PerpStatesView = {
    ...perpStatesSample(),
    data_state: "unavailable",
    reasons: ["not_derived", "rest_error:api.bybit.com:403"],
    computed_at: null,
    last: null,
    thresholds: null,
    blocks: [],
    tail: null,
    tables: [],
    covered_days: null,
    collecting: null,
    qc: [],
    series_missing: [],
  };
  show({ view });
  expect(await screen.findByText("Perp states unavailable")).toBeTruthy();
  expect(
    screen.getByText(
      "Not derived yet: the worker has not finished its first round · api.bybit.com failing (403); older data kept",
    ),
  ).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.queryByText(/Resolution 10m/)).toBeNull();
});

it.each([
  ["delayed", "Data is delayed · data through 2026-10-17 11:00 UTC"],
  ["stale", "Data is stale · data through 2026-10-17 11:00 UTC"],
] as const)(
  "warns when the view is %s and keeps the table",
  async (state, warning) => {
    show({ view: { ...perpStatesSample(), data_state: state } });
    expect(await screen.findByText(warning)).toBeTruthy();
    expect(screen.getByText(tableTitle)).toBeTruthy();
  },
);

it("lists the failed QC checks in words", async () => {
  show({ view: perpStatesSample("qc") });
  expect(
    await screen.findByText(
      "QC 3 failed: Binance OI gap of 60 min (limit 30), Bybit OI over 1% missing, archive OI days quarantined: 1",
    ),
  ).toBeTruthy();
  expect(screen.getByText(tableTitle)).toBeTruthy();
});

it("names a missing series and a failing host in the reasons", async () => {
  show({
    view: {
      ...perpStatesSample(),
      reasons: [
        "series_missing:bybit:oi",
        "rest_error:fapi.binance.com:429",
        "something_new",
      ],
    },
  });
  expect(
    await screen.findByText(
      "No Bybit OI in the last 90 days · fapi.binance.com failing (429); older data kept · something_new",
    ),
  ).toBeTruthy();
});

it("keeps three columns on a narrow screen and folds What it is into details", async () => {
  viewport(false);
  show();
  await screen.findByText(tableTitle);
  expect(window.matchMedia).toHaveBeenCalledWith("(min-width: 601px)");
  expect(columns()).toEqual(["State", "Prob. [30d]", "Max move"]);
  expect(cellsOf(bodyRows()[0])).toEqual([
    "Short squeeze",
    "4%",
    "+2.89% · 4h",
  ]);
  const details = document.querySelector<HTMLDetailsElement>(
    "details.wh-perp-what",
  )!;
  expect(details.open).toBe(false);
  expect(details.querySelector("summary")?.textContent).toBe("What it is");
  expect(within(details).getByText("Shorts forced to buy back")).toBeTruthy();
  expect(within(details).getByText("None of the above")).toBeTruthy();
});

it("keeps Table 1's three notes expanded, outside any details element, on every width", async () => {
  for (const wide of [true, false]) {
    viewport(wide);
    const { container } = show();
    await screen.findByText(tableTitle);
    const headings = [...container.querySelectorAll(".wh-perp-read h4")];
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "What it shows",
      "What extreme values imply",
      "How to read",
    ]);
    for (const heading of headings) {
      expect(heading.closest("details")).toBeNull();
      expect((heading.parentElement?.textContent ?? "").length).toBeGreaterThan(
        (heading.textContent ?? "").length + 40,
      );
    }
    cleanup();
  }
});

it("has Chinese copy for every perp key, written apart from the English", () => {
  const keys = Object.keys(messages.en).filter((key) =>
    key.startsWith("perp."),
  );
  expect(keys.length).toBeGreaterThan(40);
  for (const key of keys) {
    const zh = messages.zh[key as keyof typeof messages.zh];
    expect(zh.length).toBeGreaterThan(0);
  }
  for (const key of [
    "perp.table.shows",
    "perp.table.implies",
    "perp.table.how",
  ])
    expect(messages.zh[key as keyof typeof messages.zh]).not.toBe(
      messages.en[key as keyof typeof messages.en],
    );
});

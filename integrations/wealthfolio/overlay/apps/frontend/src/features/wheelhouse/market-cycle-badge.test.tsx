import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import MarketPage from "./market-page";
import { cycleSample, levelsSample } from "./onchain-contract";

const mocks = vi.hoisted(() => ({
  workspace: vi.fn(),
  cycle: vi.fn(),
  levels: vi.fn(),
}));
vi.mock("./market-chart", () => ({ MarketChart: () => null }));
vi.mock("./demark-details", () => ({ DemarkDetails: () => null }));
vi.mock("./regime-check", () => ({ RegimeCheck: () => null }));
vi.mock("./language-toggle", () => ({ LanguageToggle: () => null }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getServiceStatus: async () => ({ service_version: "test" }),
  getWorkspace: mocks.workspace,
  getSnapshots: async () => [],
  getSnapshot: () => new Promise(() => {}),
  getJobEvents: async () => [],
  submitJob: () => new Promise(() => {}),
  getOnchainCycle: mocks.cycle,
  getOnchainLevels: mocks.levels,
}));

const scrollIntoView = vi.fn();
beforeEach(() => {
  // jsdom has no layout, so it does not implement scrollIntoView.
  Element.prototype.scrollIntoView = scrollIntoView;
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

// An Error rejects, a Promise is returned as is (to stay pending), anything else resolves.
type Reply = unknown;
function reply(mock: ReturnType<typeof vi.fn>, value: Reply) {
  if (value instanceof Error) mock.mockRejectedValue(value);
  else if (value instanceof Promise) mock.mockReturnValue(value);
  else mock.mockResolvedValue(value);
}

function open(search: string, data: { cycle?: Reply; levels?: Reply } = {}) {
  mocks.workspace.mockResolvedValue({
    snapshot: null,
    latest_job: null,
    refresh_job: null,
    schedule: null,
    current_state: "unavailable",
  });
  reply(mocks.cycle, data.cycle ?? cycleSample);
  reply(mocks.levels, data.levels ?? levelsSample);
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

const badge = () => screen.queryByText("Cycle · Breakout · day 24");
const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

const cycleSection = () =>
  document.getElementById("wh-onchain-cycle") as HTMLDetailsElement | null;

it("shows the badge for the live BTC view and scrolls to the cycle section", async () => {
  open("?symbol=BTCUSDT&method=td");
  fireEvent.click(await screen.findByText("Cycle · Breakout · day 24"));
  await waitFor(() =>
    expect(screen.getByRole("tab", { selected: true }).id).toBe(
      "wh-tab-levels",
    ),
  );
  await waitFor(() => expect(scrollIntoView).toHaveBeenCalledOnce());
  expect(scrollIntoView.mock.contexts[0]).toBe(cycleSection());
  // The request is consumed: later renders do not scroll again.
  await settle();
  expect(scrollIntoView).toHaveBeenCalledOnce();
});

it("opens the collapsed cycle section when the badge takes the reader to it", async () => {
  open("?symbol=BTCUSDT&method=td");
  fireEvent.click(await screen.findByText("Cycle · Breakout · day 24"));
  await waitFor(() => expect(scrollIntoView).toHaveBeenCalledOnce());
  // jsdom reports a narrow screen, where the section starts collapsed.
  expect(cycleSection()?.open).toBe(true);
});

it("renders the cycle section as soon as Key levels opens, before the data arrives", () => {
  open("?symbol=BTCUSDT&method=levels", {
    cycle: new Promise(() => {}),
    levels: new Promise(() => {}),
  });
  const section = cycleSection();
  expect(section).toBeTruthy();
  expect(section?.tabIndex).toBe(-1);
  expect(within(section!).getByText("Loading cycle…")).toBeTruthy();
});

it("keeps the cycle section when the on-chain requests fail", async () => {
  open("?symbol=BTCUSDT&method=levels", {
    cycle: new Error("down"),
    levels: new Error("down"),
  });
  expect(
    await within(cycleSection()!).findByText("Cycle unavailable"),
  ).toBeTruthy();
});

it("has no cycle section for ETH or a saved snapshot", async () => {
  open("?symbol=ETHUSDT&method=levels");
  await settle();
  expect(cycleSection()).toBeNull();
  cleanup();
  open(`?symbol=BTCUSDT&method=levels&snapshot=${"a".repeat(64)}`);
  await settle();
  expect(cycleSection()).toBeNull();
});

it("hides the badge for ETH", async () => {
  open("?symbol=ETHUSDT");
  await settle();
  expect(badge()).toBeNull();
});

it("hides the badge while a saved snapshot is selected", async () => {
  open(`?symbol=BTCUSDT&snapshot=${"a".repeat(64)}`);
  await settle();
  expect(badge()).toBeNull();
});

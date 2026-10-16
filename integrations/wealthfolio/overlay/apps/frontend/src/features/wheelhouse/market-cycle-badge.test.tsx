import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import MarketPage from "./market-page";
import { cycleSample } from "./onchain-contract";

const mocks = vi.hoisted(() => ({ workspace: vi.fn(), cycle: vi.fn() }));
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
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function open(search: string) {
  mocks.workspace.mockResolvedValue({
    snapshot: null,
    latest_job: null,
    refresh_job: null,
    schedule: null,
    current_state: "unavailable",
  });
  mocks.cycle.mockResolvedValue(cycleSample);
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

it("shows the badge for the live BTC view and opens Key levels on the cycle panel", async () => {
  const panel = document.createElement("div");
  panel.id = "wh-onchain-cycle";
  panel.scrollIntoView = vi.fn();
  document.body.append(panel);
  try {
    open("?symbol=BTCUSDT&method=td");
    fireEvent.click(await screen.findByText("Cycle · Breakout · day 24"));
    await waitFor(() =>
      expect(screen.getByRole("tab", { selected: true }).id).toBe(
        "wh-tab-levels",
      ),
    );
    await waitFor(() => expect(panel.scrollIntoView).toHaveBeenCalledOnce());
    // The request is consumed: later renders do not scroll again.
    await settle();
    expect(panel.scrollIntoView).toHaveBeenCalledOnce();
  } finally {
    panel.remove();
  }
});

it("switches to Key levels even before the cycle panel exists", async () => {
  open("?symbol=BTCUSDT&method=td");
  fireEvent.click(await screen.findByText("Cycle · Breakout · day 24"));
  await waitFor(() =>
    expect(screen.getByRole("tab", { selected: true }).id).toBe(
      "wh-tab-levels",
    ),
  );
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

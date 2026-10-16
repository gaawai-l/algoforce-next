import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { CycleView } from "./onchain-contract";
import { cycleSample } from "./onchain-contract";
import { CycleBadge } from "./cycle-badge";
import { messages } from "./i18n";

const mocks = vi.hoisted(() => ({ cycle: vi.fn() }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getOnchainCycle: mocks.cycle,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show(
  view: CycleView | Error,
  props: { symbol?: "BTCUSDT" | "ETHUSDT" | "MUUSDT"; live?: boolean } = {},
  onOpen = vi.fn(),
) {
  if (view instanceof Error) mocks.cycle.mockRejectedValue(view);
  else mocks.cycle.mockResolvedValue(view);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <CycleBadge
        symbol={props.symbol ?? "BTCUSDT"}
        live={props.live ?? true}
        onOpen={onOpen}
      />
    </QueryClientProvider>,
  );
  return onOpen;
}

it("shows the state, its day count, the start date and the forming marker", async () => {
  show(cycleSample);
  const badge = (await screen.findByText("Cycle · Breakout · day 24")).closest(
    "button",
  );
  expect(screen.getByText("since 23 Sep")).toBeTruthy();
  expect(screen.getByText("includes today (forming)")).toBeTruthy();
  expect(badge?.classList.contains("wh-cycle")).toBe(true);
  expect(badge?.classList.contains("wh-cycle--muted")).toBe(false);
});

it("omits the forming marker once the latest row is closed", async () => {
  show({ ...cycleSample, forming_at: null });
  await screen.findByText("Cycle · Breakout · day 24");
  expect(screen.queryByText("includes today (forming)")).toBeNull();
});

it("keeps a fresh badge normal when the service only reports a note", async () => {
  show({ ...cycleSample, reasons: ["series_missing:true_market_mean"] });
  const badge = (await screen.findByText("Cycle · Breakout · day 24")).closest(
    "button",
  );
  expect(badge?.classList.contains("wh-cycle--muted")).toBe(false);
  expect(screen.queryByText("Cycle unavailable")).toBeNull();
});

it("renders nothing for other symbols and never queries the service for them", async () => {
  show(cycleSample, { symbol: "ETHUSDT" });
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(document.querySelector(".wh-cycle")).toBeNull();
  expect(mocks.cycle).not.toHaveBeenCalled();
});

it("renders nothing when a saved snapshot is selected", async () => {
  show(cycleSample, { live: false });
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(document.querySelector(".wh-cycle")).toBeNull();
  expect(mocks.cycle).not.toHaveBeenCalled();
});

it("mutes a stale reading and says when it is from", async () => {
  show({
    ...cycleSample,
    data_state: "stale",
    as_of: "2026-10-14",
    forming_at: null,
  });
  const text = await screen.findByText("stale · as of 14 Oct");
  expect(text.closest("button")?.classList.contains("wh-cycle--muted")).toBe(
    true,
  );
  expect(screen.queryByText("includes today (forming)")).toBeNull();
});

it("says the cycle is unavailable and why, without inventing a day count", async () => {
  show({
    ...cycleSample,
    data_state: "unavailable",
    reasons: ["brk_unavailable"],
    forming_at: null,
    as_of: null,
    state: null,
    since: null,
    day: null,
    components: [],
    episodes: [],
    changes: null,
  });
  const title = await screen.findByText("Cycle unavailable");
  expect(title.closest("button")?.classList.contains("wh-cycle--muted")).toBe(
    true,
  );
  expect(screen.getByText("on-chain data source unavailable")).toBeTruthy();
  expect(screen.queryByText(/day/)).toBeNull();
});

it("shows the failure when the service cannot be reached", async () => {
  show(new Error("Python service unavailable"));
  expect(await screen.findByText("Cycle unavailable")).toBeTruthy();
  expect(screen.getByText("Python service unavailable")).toBeTruthy();
});

it("calls onOpen when clicked", async () => {
  const onOpen = show(cycleSample);
  fireEvent.click(await screen.findByRole("button"));
  await waitFor(() => expect(onOpen).toHaveBeenCalledOnce());
});

it("names every cycle state in Chinese", () => {
  expect(
    ["advance", "breakout", "pressure", "repair", "breakdown", "capitulation"]
      .map(
        (state) =>
          messages.zh[`cycle.state.${state}` as keyof typeof messages.zh],
      )
      .join(" "),
  ).toBe("上行 突破 承压 修复 破位 投降");
});

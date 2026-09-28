import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CycleCheck } from "./cycle-check";
import type { MarketCycle } from "./cycle-contract";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const stats = (
  [
    "advance",
    "breakout",
    "pressure",
    "repair",
    "breakdown",
    "capitulation",
  ] as const
).map((state) => ({
  state,
  runs: state === "breakout" ? 6 : 1,
  days: state === "breakout" ? 136 : 10,
  mean_days: state === "breakout" ? 22.7 : 10,
  median_days: state === "breakout" ? 27 : 10,
  max_days: state === "breakout" ? 42 : 10,
}));
const cycle: MarketCycle = {
  source: "bitview",
  status: "fresh",
  checked_at: "2026-09-28T01:00:00Z",
  as_of: "2026-09-27",
  states: {
    state: "breakout",
    since: "2026-09-23",
    days: 5,
    changes: 42,
    depth: 0.095,
    spread: -0.056,
    multiplier: 5,
    stats,
  },
  index: {
    components: {
      unrealized: 45.2,
      realized: 67.9,
      supply: 46.1,
      young_vs_seasoned: 20.3,
    },
    composite: 44.9,
    zone: "mid",
    change: { "1d": 4.2, "7d": 9, "30d": 5.1, "90d": 33 },
  },
  pressure: {
    value: 90.04,
    history: [{ day: "2026-09-27", value: 90.04 }],
    warn: 84.5,
    confirm: 75,
    thresholds_confirmed: false,
    stage: "none",
  },
  error: null,
};

function mount(body: MarketCycle) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body))),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CycleCheck />
    </QueryClientProvider>,
  );
}

it("shows state, index, pressure and marks the author thresholds as unconfirmed", async () => {
  mount(cycle);
  await waitFor(() =>
    expect(screen.getAllByText("Breakout (突破)").length).toBeGreaterThan(0),
  );
  expect(screen.getByText(/day 5 \(since 2026-09-23\)/)).toBeTruthy();
  expect(screen.getAllByText("45").length).toBeGreaterThan(0);
  expect(screen.getByText("Mid-cycle")).toBeTruthy();
  expect(screen.getByText("90.0% · not triggered")).toBeTruthy();
  expect(screen.getByText(/basis unconfirmed/)).toBeTruthy();
  expect(screen.getByText("+4 / +9 / +5 / +33")).toBeTruthy();
  expect(screen.getByText(/42 state changes since 2015/)).toBeTruthy();
});

it("shows unavailable instead of zeros when bitview fails", async () => {
  mount({
    ...cycle,
    status: "unavailable",
    states: null,
    index: null,
    pressure: null,
    as_of: null,
    error: "bitview down",
  });
  await waitFor(() =>
    expect(screen.getByRole("alert").textContent).toBe(
      "Unavailable: bitview down",
    ),
  );
  expect(screen.queryByText("45")).toBeNull();
});

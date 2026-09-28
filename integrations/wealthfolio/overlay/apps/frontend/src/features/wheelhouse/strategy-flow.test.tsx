import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Stream } from "./client";
import { StrategyFlow } from "./strategy-flow";
import {
  DEFAULT_STATE,
  loadState,
  nextAction,
  nextRiskDir,
} from "./strategy-flow-data";

const stream = {
  source: "bybit",
  symbol: "BTCUSDT",
  timeframe: "1h",
  venue: "bybit-spot",
  market_session: "24/7",
  timezone: "UTC",
  quote_currency: "USDT",
  base_currency: "BTC",
  price_encoding: "decimal_string_18_places",
} as Stream;

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({}), { status: 500 })),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <StrategyFlow stream={stream} />
    </QueryClientProvider>,
  );
}

it("starts on AlphaBTC's defaults: early breakout, breakout fading, its option actions", () => {
  mount();
  expect(
    screen
      .getByRole("radio", { name: "Early breakout" })
      .getAttribute("aria-checked"),
  ).toBe("true");
  expect(
    screen
      .getByRole("radio", { name: "After a pump · Breakout fading" })
      .getAttribute("aria-checked"),
  ).toBe("true");
  // Near call rolls down, the other three legs roll up, on both signal sides.
  expect(screen.getAllByRole("button", { name: "Roll down" })).toHaveLength(2);
  expect(screen.getAllByRole("button", { name: "Roll up" })).toHaveLength(6);
  expect(screen.getByText(/Move near puts up, near calls down/)).toBeTruthy();
});

it("keeps manual overrides per pattern and in this browser", () => {
  mount();
  fireEvent.click(screen.getAllByRole("button", { name: "Roll down" })[0]);
  expect(screen.getAllByRole("button", { name: "Buy back" })).toHaveLength(1);
  fireEvent.click(
    screen.getByRole("radio", { name: "Before a pump · Grind-down breakout" }),
  );
  expect(screen.getByText(/awaits the author/)).toBeTruthy();
  const saved = loadState();
  expect(saved.act.decay?.["intra:nc"]).toBe("buyback");
  expect(saved.pattern.breakout).toBe("grind");
});

it("says a phase without author content is undefined instead of inventing actions", () => {
  mount();
  fireEvent.click(screen.getByRole("radio", { name: "Bull top" }));
  expect(
    screen.getAllByText("Not defined by the author yet").length,
  ).toBeGreaterThan(1);
  expect(screen.queryByRole("button", { name: "Roll up" })).toBeNull();
});

it("shows the author's backtest table labelled as not reproduced", () => {
  mount();
  const table = screen.getByRole("table");
  expect(within(table).getByText("≤ 1.5 days")).toBeTruthy();
  expect(screen.getByText(/not reproduced locally/)).toBeTruthy();
  fireEvent.click(screen.getByRole("radio", { name: "Sell call" }));
  expect(
    within(screen.getByRole("table")).getByText("≤ 1 day (75%)"),
  ).toBeTruthy();
});

it("cycles actions and directions as on AlphaBTC", () => {
  expect(["up", "down", "buyback"].map((a) => nextAction(a as "up"))).toEqual([
    "down",
    "buyback",
    "up",
  ]);
  expect(nextRiskDir("up", "up")).toBe("down");
  expect(nextRiskDir("cover", "hl")).toBe("bb");
  localStorage.setItem("wh.strategy-flow.v1", "not json");
  expect(loadState()).toEqual(DEFAULT_STATE);
});

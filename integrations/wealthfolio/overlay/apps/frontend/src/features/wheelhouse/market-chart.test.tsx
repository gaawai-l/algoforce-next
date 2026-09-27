import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { analysisSchema } from "./client";
import { defaultDemarkConfig } from "./demark-contract";
import { MarketChart } from "./market-chart";

const time = (i: number) => new Date(Date.UTC(2026, 0, 1, i)).toISOString();
const bars = Array.from({ length: 100 }, (_, i) => ({
  revision_id: `b${i}`,
  revision: 1,
  fetched_at: time(101),
  bar: {
    open_time: time(i),
    close_time: time(i + 1),
    open: "100",
    high: "102",
    low: "99",
    close: "101",
    volume: null,
    is_closed: true,
  },
}));
const baseline = analysisSchema.parse({
  snapshot_id: "baseline",
  input_hash: "input",
  stream: {
    source: "fixture",
    symbol: "BTCUSDT",
    timeframe: "1h",
    venue: "binance-spot",
    market_session: "24/7",
    timezone: "UTC",
    quote_currency: "USDT",
    base_currency: "BTC",
    price_encoding: "decimal_string_18_places",
  },
  rules: { engine_version: "baseline-v1", window: 20, demark: null },
  market_at: time(100),
  knowledge_at: time(101),
  fetched_at: time(101),
  closed_bar_time: time(100),
  forming_bar_time: null,
  expected_next_close: time(101),
  data_state: "simulated",
  mode: "retrospective",
  warmup_required: 21,
  warmup_complete: true,
  issues: [],
  bars,
  points: bars.map((b) => ({
    at: b.bar.close_time,
    revision_id: b.revision_id,
    sma: null,
    prior_high: null,
    prior_low: null,
  })),
  signal_status: "not_implemented",
  demark: null,
});
afterEach(cleanup);
describe("Sequential chart evidence", () => {
  it("distinguishes a baseline-only snapshot from a bar without an event", () => {
    render(
      <MarketChart
        analysis={baseline}
        visibleBars={100}
        showLevels={false}
        showDemark
      />,
    );
    expect(
      screen.getByText("DeMark not calculated in this snapshot"),
    ).toBeTruthy();
    expect(screen.queryByText("No Sequential event on this bar")).toBeNull();
  });
  it("keeps event and OHLC selection aligned when the visible window shrinks", () => {
    const calculated = analysisSchema.parse({
      ...baseline,
      demark: {
        config: defaultDemarkConfig,
        input_hash: "td-input",
        history_start: time(0),
        history_end: time(100),
        history_status: "window_only",
        status: "ready",
        warmup_required: 6,
        sequences: [],
        qualified13_count: 0,
        issues: [],
        events: [
          {
            sequence_id: "buy-sequence",
            side: "buy",
            kind: "setup_count",
            count: 1,
            reason: "close_vs_four_bars_earlier",
            bar: {
              revision_id: "b99",
              open_time: time(99),
              close_time: time(100),
              close: "101",
            },
          },
        ],
      },
    });
    const view = render(
      <MarketChart
        analysis={calculated}
        visibleBars={100}
        showLevels={false}
        showDemark
      />,
    );
    fireEvent.keyDown(screen.getByRole("img"), { key: "ArrowLeft" });
    expect(screen.getByText("No Sequential event on this bar")).toBeTruthy();
    view.rerender(
      <MarketChart
        analysis={calculated}
        visibleBars={50}
        showLevels={false}
        showDemark
      />,
    );
    expect(screen.getByText("buy setup count 1")).toBeTruthy();
  });
});

it("changes cached time ranges locally and exposes keyboard-adjustable boundaries", () => {
  render(
    <MarketChart analysis={baseline} visibleBars={50} showLevels={false} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "All cached" }));
  expect(screen.getByText("100 / 100 cached bars")).toBeTruthy();
  fireEvent.change(screen.getByRole("slider", { name: "Range start" }), {
    target: { value: "20" },
  });
  expect(screen.getByText("80 / 100 cached bars")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Reset" }));
  expect(screen.getByText("50 / 100 cached bars")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Last 7d" }));
  expect(screen.getByText("100 / 100 cached bars")).toBeTruthy();
  expect(
    screen.getByText(
      "Requested dates exceed cached history; showing available bars.",
    ),
  ).toBeTruthy();
});

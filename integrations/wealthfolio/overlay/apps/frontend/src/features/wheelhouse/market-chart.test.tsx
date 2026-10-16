import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { analysisSchema, stamp } from "./client";
import { defaultDemarkConfig } from "./demark-contract";
import type { RailBand } from "./levels-rail";
import { MarketChart, type ChartOverlay } from "./market-chart";

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
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
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

describe("on-chain overlays", () => {
  // Bars span 81,900..82,500, so the padded y domain is 81,840..82,560. In jsdom the chart
  // keeps its default 980x540 box: the plot ends at x = 868 and the tick column starts at 879.
  const priced = analysisSchema.parse({
    ...baseline,
    bars: bars.map((row) => ({
      ...row,
      bar: {
        ...row.bar,
        open: "82000",
        high: "82500",
        low: "81900",
        close: "82100",
      },
    })),
  });
  const RIGHT = 868;
  const TICK_COLUMN = RIGHT + 11;
  const PLOT_BOTTOM = 540 - 47;
  const axis = (container: HTMLElement) =>
    [...container.querySelectorAll("text.wh-axis")].map((n) => n.textContent);
  const label = (text: string) => screen.getByText(text);
  const num = (node: Element, name: string) => Number(node.getAttribute(name));
  const chart = (overlays: ChartOverlay[]) => (
    <MarketChart
      analysis={priced}
      visibleBars={100}
      showLevels
      overlays={overlays}
    />
  );
  const average = { id: "average", label: "Average", price: 53842.4 };
  const longTerm = { id: "long_term", label: "Long-term", price: 49242.1 };
  const shortTerm = { id: "short_term", label: "Short-term", price: 106200.25 };

  it("overlays do not change the price axis", () => {
    const plain = render(
      <MarketChart analysis={priced} visibleBars={100} showLevels />,
    );
    const before = axis(plain.container);
    const candles = plain.container.querySelectorAll("g[stroke] line").length;
    plain.unmount();
    expect(before).toContain("81,840.00");
    expect(before).toContain("82,560.00");
    const view = render(
      chart([
        average,
        shortTerm,
        { id: "median", label: "Median", price: 82200 },
      ]),
    );
    expect(axis(view.container)).toEqual(before);
    expect(view.container.querySelectorAll("g[stroke] line")).toHaveLength(
      candles,
    );
  });

  it("out-of-range overlays render edge markers", () => {
    render(chart([longTerm, average, shortTerm]));
    // One row per direction, nearest line first.
    const below = label("↓ Average $53,842 · Long-term $49,242");
    const above = label("↑ Short-term $106,200");
    expect(num(below, "y")).toBeGreaterThan(PLOT_BOTTOM);
    expect(num(above, "y")).toBeLessThan(18);
    // Out-of-range lines are never drawn inside the plot.
    expect(document.querySelectorAll("line.wh-overlay-line")).toHaveLength(0);
  });

  it("in-range overlay draws a dashed line labelled inside the plot", () => {
    const view = render(
      chart([{ id: "true_mean", label: "True mean", price: 82200 }]),
    );
    const line = view.container.querySelector("line.wh-overlay-line")!;
    expect(line.getAttribute("stroke-dasharray")).toBeTruthy();
    expect(num(line, "x2")).toBe(RIGHT);
    const text = label("True mean $82,200");
    expect(text.getAttribute("text-anchor")).toBe("end");
    expect(num(text, "x")).toBe(RIGHT - 4);
    expect(num(text, "x")).toBeLessThan(TICK_COLUMN);
    expect(num(text, "y")).toBeLessThan(num(line, "y1"));
    expect(num(line, "y1")).toBeGreaterThan(18);
    expect(num(line, "y1")).toBeLessThan(PLOT_BOTTOM);
    expect(
      view.container.querySelectorAll("text.wh-overlay-edge"),
    ).toHaveLength(0);
  });

  it("moves a colliding label below its line", () => {
    render(
      chart([
        { id: "average", label: "Average", price: 82200 },
        { id: "median", label: "Median", price: 82190 },
      ]),
    );
    const upper = label("Average $82,200");
    const lower = label("Median $82,190");
    const lowerLine = document.querySelector(
      'line.wh-overlay-line[data-overlay="median"]',
    )!;
    expect(num(upper, "y")).toBeLessThan(num(lowerLine, "y1"));
    expect(num(lower, "y")).toBeGreaterThan(num(lowerLine, "y1"));
  });

  it("splits a long edge row instead of clipping it on a narrow chart", () => {
    class Narrow {
      constructor(private cb: (entries: unknown[]) => void) {}
      observe() {
        this.cb([{ contentRect: { width: 360, height: 540 } }]);
      }
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", Narrow);
    const view = render(
      chart([
        { id: "short_term", label: "Short-term", price: 75000 },
        { id: "true_mean", label: "True mean", price: 70100 },
        { id: "median", label: "Median", price: 63400 },
        average,
        longTerm,
      ]),
    );
    const rows = [...view.container.querySelectorAll("text.wh-overlay-edge")];
    const all = rows.map((row) => row.textContent ?? "");
    expect(all.length).toBeGreaterThan(2);
    // 11px monospace is ~6.6px per character; every row must fit inside the 360px chart.
    for (const row of all) {
      expect(row.startsWith("↓")).toBe(true);
      expect(row.length * 6.6).toBeLessThanOrEqual(360 - 32);
    }
    const joined = all.join(" ");
    for (const name of [
      "True mean",
      "Short-term",
      "Average",
      "Long-term",
      "Median",
    ])
      expect(joined).toContain(name);
    // Nearest line first; the rows stack upward from the bottom edge.
    expect(all[0]).toMatch(/^↓ Short-term/);
    const ys = rows.map((row) => num(row, "y"));
    expect(ys).toEqual([...ys].sort((a, b) => b - a));
  });

  it("names the on-chain lines in the legend only while they are shown", () => {
    const view = render(chart([average]));
    expect(screen.getByText(/on-chain cost lines/i)).toBeTruthy();
    view.rerender(
      <MarketChart analysis={priced} visibleBars={100} showLevels />,
    );
    expect(screen.queryByText(/on-chain cost lines/i)).toBeNull();
  });

  describe("price rail", () => {
    const sth2: RailBand = {
      id: "sth-2",
      cohort: "sth",
      index: 2,
      price: 82250,
      low: 77264.5,
      high: 87235.5,
      strength: 1,
      btc: 1910000,
      share: 0.521,
    };
    const far: RailBand = {
      id: "lth-1",
      cohort: "lth",
      index: 1,
      price: 60000,
      low: 58000,
      high: 62000,
      strength: 0.5,
      btc: 880000,
      share: 0.069,
    };
    const railed = (rail?: RailBand[], overlays?: ChartOverlay[]) => (
      <MarketChart
        analysis={priced}
        visibleBars={100}
        showLevels
        overlays={overlays}
        rail={rail}
      />
    );
    const svg = (container: HTMLElement) =>
      container.querySelector("svg.wh-chart")!;
    // The five price ticks sit in the grid groups; the date labels are direct svg children.
    const tickX = (container: HTMLElement) =>
      [...container.querySelectorAll("svg > g > text.wh-axis")].map((n) =>
        num(n, "x"),
      );
    const candleX = (container: HTMLElement) =>
      [...container.querySelectorAll("g[stroke] > line")].map((n) =>
        num(n, "x1"),
      );
    const gridRight = (container: HTMLElement) =>
      num(container.querySelector("svg > g > line")!, "x2");
    const ohlc = (container: HTMLElement) =>
      container.querySelector(".wh-chart-readout")!.textContent;

    it("adds no rail, read-out or group role without a rail", () => {
      const view = render(railed());
      expect(screen.queryByRole("list")).toBeNull();
      expect(screen.queryByRole("status")).toBeNull();
      expect(svg(view.container).getAttribute("role")).toBe("img");
    });

    it("narrows the plot by the rail but keeps the tick column and bar count", () => {
      const plain = render(railed());
      const ticks = tickX(plain.container);
      const candles = candleX(plain.container);
      plain.unmount();
      expect(ticks).toEqual(Array(5).fill(TICK_COLUMN));
      const view = render(railed([]));
      expect(tickX(view.container)).toEqual(ticks);
      expect(gridRight(view.container)).toBe(RIGHT - 28);
      const after = candleX(view.container);
      expect(after).toHaveLength(candles.length);
      // The plot loses 28px; the last of 100 candle centres sits at 99.5 / 100 of it.
      expect(candles.at(-1)! - after.at(-1)!).toBeCloseTo((28 * 99.5) / 100);
      expect(svg(view.container).getAttribute("role")).toBe("group");
      expect(screen.getByRole("status")).toBeTruthy();
    });

    it("uses a 16px rail on a narrow chart", () => {
      class Narrow {
        constructor(private cb: (entries: unknown[]) => void) {}
        observe() {
          this.cb([{ contentRect: { width: 500, height: 540 } }]);
        }
        disconnect() {}
      }
      vi.stubGlobal("ResizeObserver", Narrow);
      const plain = render(railed());
      const ticks = tickX(plain.container);
      plain.unmount();
      const view = render(railed([]));
      expect(
        num(view.container.querySelector(".wh-rail-track")!, "width"),
      ).toBe(16);
      expect(tickX(view.container)).toEqual(ticks);
      expect(gridRight(view.container)).toBe(16 + (500 - 128 - 16));
    });

    it("ignores pointer moves over the rail", () => {
      const view = render(railed([]));
      const chart = svg(view.container);
      vi.spyOn(chart, "getBoundingClientRect").mockReturnValue(
        new DOMRect(0, 0, 980, 540),
      );
      fireEvent.keyDown(chart, { key: "ArrowLeft" });
      const selected = ohlc(view.container);
      expect(selected).toContain(stamp(time(98)));
      fireEvent.pointerMove(chart, { clientX: RIGHT - 28 + 10 });
      expect(ohlc(view.container)).toBe(selected);
      fireEvent.pointerMove(chart, { clientX: 20 });
      expect(ohlc(view.container)).toContain(stamp(time(0)));
    });

    it("ignores pointer moves over the tick column without a rail", () => {
      const view = render(railed());
      const chart = svg(view.container);
      vi.spyOn(chart, "getBoundingClientRect").mockReturnValue(
        new DOMRect(0, 0, 980, 540),
      );
      fireEvent.keyDown(chart, { key: "ArrowLeft" });
      const selected = ohlc(view.container);
      expect(selected).toContain(stamp(time(98)));
      fireEvent.pointerMove(chart, { clientX: RIGHT + 10 });
      expect(ohlc(view.container)).toBe(selected);
    });

    it("clears the read-out when the active band leaves the rail", () => {
      const view = render(railed([sth2]));
      act(() => screen.getByRole("listitem", { name: /STH K2/ }).focus());
      expect(screen.getByRole("status").textContent).toContain("STH K2");
      view.rerender(railed([]));
      expect(screen.getByRole("status").textContent).toBe("");
    });

    it("clears the read-out when a refresh moves the active band out of range", () => {
      const view = render(railed([sth2]));
      act(() => screen.getByRole("listitem", { name: /STH K2/ }).focus());
      view.rerender(railed([{ ...sth2, low: 90000, high: 95000 }]));
      expect(screen.getByRole("status").textContent).toBe("");
      expect(view.container.querySelector(".wh-rail-spread")).toBeNull();
      view.rerender(railed([sth2]));
      expect(screen.getByRole("status").textContent).toBe("");
    });

    it("clears the read-out when the rail goes away and comes back", () => {
      const view = render(railed([sth2]));
      act(() => screen.getByRole("listitem", { name: /STH K2/ }).focus());
      expect(screen.getByRole("status").textContent).toContain("STH K2");
      // A method switch keeps the chart mounted and takes the rail away.
      view.rerender(railed(undefined));
      expect(screen.queryByRole("status")).toBeNull();
      view.rerender(railed([sth2]));
      expect(screen.getByRole("status").textContent).toBe("");
      expect(view.container.querySelector(".wh-rail-spread")).toBeNull();
    });

    it("draws only bands inside the price range and keeps the axis", () => {
      const line = { id: "true_mean", label: "True mean", price: 82200 };
      const base = render(railed([], [line]));
      const lineY = num(
        base.container.querySelector("line.wh-overlay-line")!,
        "y1",
      );
      const ticks = axis(base.container);
      base.unmount();
      const view = render(railed([sth2, far], [line]));
      expect(screen.getAllByRole("listitem")).toHaveLength(1);
      expect(
        num(view.container.querySelector("line.wh-overlay-line")!, "y1"),
      ).toBe(lineY);
      expect(axis(view.container)).toEqual(ticks);
    });

    it("reads out the focused band and keeps arrow keys on it", () => {
      const view = render(railed([sth2]));
      const selected = ohlc(view.container);
      const item = screen.getByRole("listitem", { name: /STH K2/ });
      act(() => item.focus());
      expect(view.container.querySelector(".wh-rail-spread")).not.toBeNull();
      const status = screen.getByRole("status");
      expect(status.textContent).toBe(
        "STH K2 · $82,250 · width $9,971 · 1.91M BTC (52.1%) · strength 100%",
      );
      fireEvent.keyDown(item, { key: "ArrowLeft" });
      expect(ohlc(view.container)).toBe(selected);
      act(() => item.blur());
      expect(view.container.querySelector(".wh-rail-spread")).toBeNull();
      expect(status.textContent).not.toContain("STH K2");
      expect(status.textContent).not.toContain("$82,250");
    });
  });
});

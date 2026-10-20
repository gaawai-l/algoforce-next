import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { sizeCohortsSchema, type SizeCohortsView, type WindowKey } from "./onchain-contract";
import {
  SUPPLY_DEFAULT,
  axis,
  band,
  cohortRows,
  supplyLabel,
  supplyLegend,
  supplyPlot,
  tickLabel,
} from "./size-cohorts";
import expected from "./size-cohorts-expected.json";
import raw from "./size-cohorts-sample.json";
import { SizeCohortsCharts } from "./size-cohorts-charts";

const mocks = vi.hoisted(() => ({ sizes: vi.fn() }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getSizeCohorts: mocks.sizes,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

// The local service's size cohorts at 2026-10-19 06:00Z (Task 3's sample). It has no missing
// cell and an empty no_block: every test of a missing value edits a copy of it.
const sample = sizeCohortsSchema.parse(raw);
const TITLE5 = "Chart 5 — Net Supply Change By Size Cohorts";
const TITLE6 = "Chart 6 — Net Realized Profit & Loss By Size Cohorts";
const HINT = "Hover a row, or focus the chart and use the up and down arrow keys, to read it";
const NO_BLOCK =
  "No block was mined in the hour this 7d window starts from, so there is nothing to compare against. It usually fills in within an hour or two, once the window's start moves past that hour.";
const MISSING = "—";
const GROUP_NAMES = ["Large entities", "Mid-size entities", "Small entities", "Retail"];

// A copy of the sample with the given bands' cells of one window all null.
function blanked(win: WindowKey, bands: number[], noBlock: WindowKey[] = []): SizeCohortsView {
  const copy = structuredClone(raw) as SizeCohortsView;
  for (const i of bands)
    Object.assign(copy.bands[i].windows.find((cell) => cell.window === win)!, {
      supply_change: null,
      profit: null,
      loss: null,
    });
  return sizeCohortsSchema.parse({ ...copy, no_block: noBlock });
}
const ALL_BANDS = sample.bands.map((_, i) => i);

function show(view: SizeCohortsView | Error | "pending" = sample) {
  if (view === "pending") mocks.sizes.mockReturnValue(new Promise(() => {}));
  else if (view instanceof Error) mocks.sizes.mockRejectedValue(view);
  else mocks.sizes.mockResolvedValue(view);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <SizeCohortsCharts />
      </QueryClientProvider>,
    ),
  };
}

// A poll's result, as the 5-minute refetch delivers it (observers hear of it on the next tick).
const poll = (client: QueryClient, view: SizeCohortsView) =>
  act(async () => {
    client.setQueryData(["wh", "onchain", "size-cohorts"], view);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

// The chart's width as useChartWidth reads it, reported as soon as it is observed.
function stubWidth(width: number) {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private callback: ResizeObserverCallback) {}
      observe() {
        this.callback(
          [{ contentRect: { width } } as ResizeObserverEntry],
          this as unknown as ResizeObserver,
        );
      }
      disconnect() {}
    },
  );
}

type Chart = "supply" | "pnl";
const panel = (chart: Chart) =>
  document.querySelector<HTMLElement>(`[data-chart="sizes-${chart}"]`)!;
const svg = (chart: Chart) => panel(chart).querySelector<SVGSVGElement>("svg")!;
const texts = (chart: Chart, selector: string) =>
  [...panel(chart).querySelectorAll(selector)].map((node) => node.textContent);
const values = (chart: Chart) => texts(chart, ".wh-sc-val");
const rowNames = (chart: Chart) => texts(chart, ".wh-sc-row");
const bars = (chart: Chart) => panel(chart).querySelectorAll("rect.wh-sc-bar");
const legend = (chart: Chart) => texts(chart, ".wh-seller-legend b");
const readout = (chart: Chart) => panel(chart).querySelector(".wh-sc-read")!.textContent;
const group = (chart: Chart, name: string) =>
  within(within(panel(chart)).getByRole("group", { name }));
const pick = (chart: Chart, name: string, option: string) =>
  fireEvent.click(group(chart, name).getByRole("button", { name: option }));
const pressed = (chart: Chart, name: string) =>
  group(chart, name)
    .getAllByRole("button")
    .filter((button) => button.getAttribute("aria-pressed") === "true")
    .map((button) => button.textContent);
const options = (chart: Chart, name: string) =>
  group(chart, name)
    .getAllByRole("button")
    .map((button) => button.textContent);
const key = (chart: Chart, name: string) => fireEvent.keyDown(svg(chart), { key: name });

// Source: the original page's markup and state (A:2029, A:2196; A:507-508 for the View order).
it("opens on the original defaults", async () => {
  show();
  await screen.findByText(TITLE5);
  expect(within(panel("supply")).getByRole("heading", { level: 3 }).textContent).toBe(TITLE5);
  expect(within(panel("pnl")).getByRole("heading", { level: 3 }).textContent).toBe(TITLE6);
  expect(pressed("supply", "Window")).toEqual(["7d"]);
  expect(pressed("supply", "Breakdown")).toEqual(["Entities"]);
  expect(pressed("supply", "Scale")).toEqual(["BTC"]);
  expect(pressed("pnl", "Window")).toEqual(["7d"]);
  expect(pressed("pnl", "Breakdown")).toEqual(["Entities"]);
  expect(pressed("pnl", "View")).toEqual(["Gross"]);
  expect(pressed("pnl", "Scale")).toEqual(["USD"]);
  expect(options("supply", "Window")).toEqual(["1d", "7d", "30d", "90d"]);
  expect(options("supply", "Breakdown")).toEqual(["Bands", "Entities"]);
  expect(options("supply", "Scale")).toEqual(["BTC", "% of band"]);
  expect(options("pnl", "View")).toEqual(["Net", "Gross"]);
  expect(options("pnl", "Scale")).toEqual(["USD", "% of realized cap"]);
  // Chart 5 sits above Chart 6.
  expect(
    panel("supply").compareDocumentPosition(panel("pnl")) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

// Source: page-recorded (SR-5.md:24-26, SR-6.md:23-25), via Task 4's expected readings.
it("draws the default readings", async () => {
  show();
  await screen.findByText(TITLE5);
  expect(rowNames("supply")).toEqual(GROUP_NAMES);
  expect(values("supply")).toEqual(expected.supply[0].labels);
  expect(legend("supply")).toEqual(expected.supply[0].legend);
  expect(bars("supply")).toHaveLength(4);
  expect(rowNames("pnl")).toEqual(GROUP_NAMES);
  expect(values("pnl")).toEqual(expected.pnl[0].labels);
  expect(legend("pnl")).toEqual(expected.pnl[0].legend);
  expect(bars("pnl")).toHaveLength(8);
  expect(panel("pnl").querySelectorAll(".wh-sc-tick")).toHaveLength(4);
  expect(texts("pnl", "svg text").filter((label) => label === "net")).toHaveLength(1);
  expect(texts("supply", "svg text").filter((label) => label === "net")).toHaveLength(0);
  expect(texts("supply", ".wh-sc-sides span")).toEqual([
    "BTC ← Net distribution",
    "Net accumulation → BTC",
  ]);
  expect(texts("pnl", ".wh-sc-sides span")).toEqual([
    "USD ← Loss booked",
    "Profit booked → USD",
  ]);
  expect(texts("supply", ".wh-seller-legend .wh-seller-key")).toEqual([
    `Net accumulation ${expected.supply[0].legend![0]}`,
    `Net distribution ${expected.supply[0].legend![1]}`,
    `Net (issuance) ${expected.supply[0].legend![2]}`,
  ]);
  expect(readout("supply")).toBe(HINT);
  expect(readout("pnl")).toBe(HINT);
});

// Source: the brief (a plot 480px wide or more asks for 7 ticks: 1000 − 164 − 158 = 678).
it("puts seven ticks under a 1000px chart", async () => {
  stubWidth(1000);
  show();
  await screen.findByText(TITLE5);
  const scale = axis(supplyPlot(cohortRows(sample, "groups"), SUPPLY_DEFAULT), 7)!;
  const fmt = (v: number) => supplyLabel(v, "btc");
  expect(texts("supply", ".wh-seller-tick")).toEqual(scale.ticks.map((v) => tickLabel(v, fmt)));
  expect(scale.ticks).toHaveLength(7);
});

// Source: the brief (jsdom's 720px chart is the wide layout with 3 ticks, "0" at zero).
it("puts three ticks under a 720px chart", async () => {
  show();
  await screen.findByText(TITLE5);
  const scale = axis(supplyPlot(cohortRows(sample, "groups"), SUPPLY_DEFAULT), 3)!;
  const fmt = (v: number) => supplyLabel(v, "btc");
  expect(scale.ticks).toHaveLength(3);
  expect(texts("supply", ".wh-seller-tick")).toEqual(scale.ticks.map((v) => tickLabel(v, fmt)));
  expect(texts("supply", ".wh-seller-tick")).toContain("0");
  // A grid line for each tick but 0, which has the zero line.
  expect(panel("supply").querySelectorAll(".wh-sc-grid")).toHaveLength(2);
  expect(panel("supply").querySelectorAll(".wh-sc-zero")).toHaveLength(1);
  expect(svg("supply").getAttribute("data-compact")).toBe("false");
  expect(svg("supply").getAttribute("viewBox")).toBe("0 0 720 338");
});

const num = (node: Element, name: string) => Number(node.getAttribute(name));

// Source: the original page's code: bars from the zero line, labels 7px past the tip (A:2083-2100),
// Gross labels at plotW + 12 under a "net" head, net ticks 3px past the row (A:2286-2316); the
// 0.8px bars of a band that booked nothing are page-recorded (SR-6.md:28).
it("places bars, ticks and labels as the original", async () => {
  show();
  await screen.findByText(TITLE5);
  // 720px: the plot is 720 − 164 − 158 = 398 wide and 338 − 16 − 26 = 296 tall.
  const zero = num(panel("supply").querySelector(".wh-sc-zero")!, "x1");
  expect(zero).toBe(199);
  const rowBand = band(4, 296, 0.28);
  const plot = supplyPlot(cohortRows(sample, "groups"), SUPPLY_DEFAULT);
  const labels = [...panel("supply").querySelectorAll(".wh-sc-val")];
  [...bars("supply")].forEach((bar, i) => {
    const [x, y, width, height] = ["x", "y", "width", "height"].map((name) => num(bar, name));
    expect(y).toBeCloseTo(rowBand.start + i * rowBand.step, 1);
    expect(height).toBeCloseTo(rowBand.width, 1);
    const label = labels[i];
    expect(num(label, "y")).toBeCloseTo(y + height / 2 + 3.5, 1);
    if (plot[i].value! >= 0) {
      expect(x).toBeCloseTo(zero, 1);
      expect(num(label, "x")).toBeCloseTo(x + width + 7, 1);
      expect(label.getAttribute("text-anchor")).toBe("start");
    } else {
      expect(x + width).toBeCloseTo(zero, 1);
      expect(num(label, "x")).toBeCloseTo(x - 7, 1);
      expect(label.getAttribute("text-anchor")).toBe("end");
    }
  });
  for (const name of panel("supply").querySelectorAll(".wh-sc-row"))
    expect([name.getAttribute("x"), name.getAttribute("text-anchor")]).toEqual(["-10", "end"]);
  for (const label of panel("pnl").querySelectorAll(".wh-sc-val"))
    expect([label.getAttribute("x"), label.getAttribute("text-anchor")]).toEqual(["410", "start"]);
  const head = [...panel("pnl").querySelectorAll("svg text")].find((t) => t.textContent === "net")!;
  expect([head.getAttribute("x"), head.getAttribute("y"), head.getAttribute("text-anchor")]).toEqual(
    ["410", "-4", "start"],
  );
  for (const row of panel("pnl").querySelectorAll("[data-row]")) {
    const [profit, loss] = [...row.querySelectorAll("rect")];
    expect(profit.getAttribute("class")).toBe("wh-sc-bar wh-sc-bar--pos");
    expect(loss.getAttribute("class")).toBe("wh-sc-bar wh-sc-bar--neg");
    const tick = row.querySelector(".wh-sc-tick")!;
    expect(num(tick, "y1")).toBeCloseTo(num(profit, "y") - 3, 1);
    expect(num(tick, "y2")).toBeCloseTo(num(profit, "y") + num(profit, "height") + 3, 1);
    expect(num(tick, "x1")).toBeCloseTo(num(loss, "x") + num(profit, "width"), 1);
  }
  pick("pnl", "Breakdown", "Bands");
  const nothing = panel("pnl").querySelector('[data-row="addrs_over_100k_btc"]')!;
  expect([...nothing.querySelectorAll("rect")].map((bar) => bar.getAttribute("width"))).toEqual([
    "0.8",
    "0.8",
  ]);
  // A loss of 0 is still the loss bar (A:2877), though its value is −0.
  expect([...nothing.querySelectorAll("rect")].map((bar) => bar.getAttribute("class"))).toEqual([
    "wh-sc-bar wh-sc-bar--pos",
    "wh-sc-bar wh-sc-bar--neg",
  ]);
  // The longest bar negative: at 90d as % of band, Retail's −1.732% (page-recorded, SR-5.md). Its
  // tip is 0.12 / 2.24 of the plot from the left, at 21.32, so 7px left of it the 7-character label
  // would run into "Retail" (the final review's M1): it goes inside the bar's end instead. Small's
  // shorter −0.437% keeps its label outside.
  pick("supply", "Window", "90d");
  pick("supply", "Scale", "% of band");
  expect(values("supply")).toEqual(expected.supply[7].labels);
  const [, , small, retail] = [...bars("supply")];
  const [, , smallLabel, retailLabel] = [...panel("supply").querySelectorAll(".wh-sc-val")];
  expect(num(retail, "x")).toBeCloseTo(21.32, 2);
  expect(num(retailLabel, "x")).toBeCloseTo(28.32, 2);
  expect(retailLabel.getAttribute("text-anchor")).toBe("start");
  expect(retailLabel.getAttribute("class")).toBe("wh-sc-val wh-sc-val--in");
  expect(num(smallLabel, "x")).toBeCloseTo(num(small, "x") - 7, 1);
  expect(smallLabel.getAttribute("text-anchor")).toBe("end");
  expect(smallLabel.getAttribute("class")).toBe("wh-sc-val");
});

// Source: page-recorded (SR-5.md:22, the twelve band names; SR-6.md:23-26, the % labels).
it("switches breakdown, view and scale", async () => {
  show();
  await screen.findByText(TITLE5);
  pick("supply", "Breakdown", "Bands");
  expect(rowNames("supply")).toHaveLength(12);
  expect(rowNames("supply")[0]).toBe("over 100k BTC");
  // Each chart has its own controls.
  expect(rowNames("pnl")).toEqual(GROUP_NAMES);
  pick("pnl", "View", "Net");
  expect(bars("pnl")).toHaveLength(4);
  expect(panel("pnl").querySelectorAll(".wh-sc-tick")).toHaveLength(0);
  expect(texts("pnl", "svg text").filter((label) => label === "net")).toHaveLength(0);
  expect(texts("pnl", ".wh-sc-sides span")).toEqual(["USD ← Net loss", "Net profit → USD"]);
  pick("pnl", "Scale", "% of realized cap");
  expect(values("pnl")).toEqual(expected.pnl[3].labels);
  expect(legend("pnl")).toEqual(expected.pnl[0].legend);
  expect(texts("pnl", ".wh-sc-sides span")).toEqual([
    "% of realized cap ← Net loss",
    "Net profit → % of realized cap",
  ]);
  pick("supply", "Breakdown", "Entities");
  pick("supply", "Scale", "% of band");
  expect(values("supply")).toEqual(expected.supply[1].labels);
  expect(legend("supply")).toEqual(expected.supply[0].legend);
  expect(texts("supply", ".wh-sc-sides span")).toEqual([
    "% of band ← Net distribution",
    "Net accumulation → % of band",
  ]);
  pick("supply", "Window", "30d");
  expect(values("supply")).toEqual(expected.supply[5].labels);
  // The legend and the reading follow the window (the legend's formula over the sample).
  expect(legend("supply")).toEqual(supplyLegend(cohortRows(sample, "groups"), "30d"));
  key("supply", "End");
  expect(readout("supply")).toContain("30d window · threshold crossings can dominate");
  pick("pnl", "Window", "1d");
  expect(legend("pnl")).toEqual(expected.pnl[4].legend);
  key("pnl", "ArrowDown");
  expect(readout("pnl")).toMatch(/ · 1d window$/);
});

// Source: page-recorded (SR-6.md:25, the Large row's tooltip).
it("reads a row from the keyboard", async () => {
  show();
  await screen.findByText(TITLE6);
  svg("pnl").focus();
  expect(document.activeElement).toBe(svg("pnl"));
  expect(svg("pnl").getAttribute("tabindex")).toBe("0");
  expect(svg("pnl").getAttribute("aria-label")).toBe(
    `${TITLE6}. Use the up and down arrow keys to read one row; Escape clears the reading.`,
  );
  key("pnl", "ArrowDown");
  for (const part of [
    "Large entities · major exchanges, treasuries",
    "Loss booked",
    "−$467.6M",
    "35% of booked value was profit · 7d window",
  ])
    expect(readout("pnl")).toContain(part);
  // The read row is shaded over its whole step, centred on its bars.
  const shade = panel("pnl").querySelector(".wh-sc-hover")!;
  const first = panel("pnl").querySelector("rect.wh-sc-bar")!;
  expect(num(shade, "y") + num(shade, "height") / 2).toBeCloseTo(
    num(first, "y") + num(first, "height") / 2,
    1,
  );
  expect(panel("pnl").querySelectorAll(".wh-sc-hover")).toHaveLength(1);
  // Chart 5 keeps its own reading.
  expect(readout("supply")).toBe(HINT);
  key("pnl", "Escape");
  expect(readout("pnl")).toBe(HINT);
  expect(panel("pnl").querySelectorAll(".wh-sc-hover")).toHaveLength(0);
  // Leaving the chart clears the reading too, as on the other Flows charts.
  key("pnl", "ArrowDown");
  fireEvent.blur(svg("pnl"));
  expect(readout("pnl")).toBe(HINT);
});

// Source: the brief (arrow keys row by row, the first press from the top or the bottom; Home, End).
it("walks the rows with the arrow keys, Home and End", async () => {
  show();
  await screen.findByText(TITLE5);
  const head = () => readout("supply").split(" · ")[0];
  key("supply", "ArrowUp");
  expect(head()).toBe("Retail");
  key("supply", "ArrowUp");
  expect(head()).toBe("Small entities");
  key("supply", "Home");
  expect(head()).toBe("Large entities");
  key("supply", "ArrowUp");
  expect(head()).toBe("Large entities");
  key("supply", "ArrowDown");
  expect(head()).toBe("Mid-size entities");
  key("supply", "End");
  expect(head()).toBe("Retail");
  key("supply", "ArrowDown");
  expect(head()).toBe("Retail");
  // Source: page-recorded (SR-5.md:30).
  key("supply", "Home");
  for (const [name, value] of expected.supplyRead.lines)
    expect(readout("supply")).toContain(`${name} ${value}`);
  expect(readout("supply")).toContain(expected.supplyRead.foot);
});

// Source: the brief (the pointer picks the row nearest by y).
it("reads the row nearest the pointer", async () => {
  show();
  await screen.findByText(TITLE5);
  const chart = svg("supply");
  chart.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 720, height: 338, right: 720, bottom: 338 }) as DOMRect;
  // 720px: 4 rows over 296px from y = 16, each 49.8px tall every 69.2px from 19.4 (layout, band).
  const at = (clientY: number) => {
    fireEvent.pointerMove(chart, { clientX: 300, clientY, pointerType: "mouse" });
    return readout("supply").split(" · ")[0];
  };
  expect(at(2)).toBe("Large entities");
  expect(at(16 + 19.4 + 49.8 + 5)).toBe("Large entities");
  // In the gap just above Mid-size: its middle is nearer than Large's.
  expect(at(16 + 19.4 + 69.2 - 2)).toBe("Mid-size entities");
  expect(at(16 + 19.4 + 69.2 + 5)).toBe("Mid-size entities");
  expect(at(16 + 19.4 + 2 * 69.2 + 25)).toBe("Small entities");
  expect(at(337)).toBe("Retail");
  fireEvent.pointerLeave(chart, { pointerType: "mouse" });
  expect(readout("supply")).toBe(HINT);
});

// Source: the brief (a missing value prints "—" and draws no bar; the legend over it is "—").
it("shows a dash and no bar for a missing row", async () => {
  show(blanked("7d", [11]));
  await screen.findByText(TITLE5);
  expect(values("supply")).toEqual([MISSING, ...expected.supply[0].labels.slice(1)]);
  // The dash sits just right of the zero line (mid-plot: 398 / 2 at 720px).
  const dash = panel("supply").querySelector(".wh-sc-val")!;
  expect([dash.getAttribute("x"), dash.getAttribute("text-anchor")]).toEqual(["206", "start"]);
  expect(panel("supply").querySelector('[data-row="large"] rect')).toBeNull();
  expect(panel("supply").querySelector('[data-row="mid"] rect')).not.toBeNull();
  expect(bars("supply")).toHaveLength(3);
  expect(legend("supply")).toEqual([MISSING, MISSING, MISSING]);
  expect(values("pnl")).toEqual([MISSING, ...expected.pnl[0].labels.slice(1)]);
  expect(panel("pnl").querySelector('[data-row="large"] .wh-sc-tick')).toBeNull();
  expect(legend("pnl")).toEqual([MISSING, MISSING, MISSING]);
  expect(screen.queryByText(/No block was mined/)).toBeNull();
  expect(screen.queryByText("No data for this chart")).toBeNull();
  pick("supply", "Window", "1d");
  expect(values("supply")).toEqual(expected.supply[2].labels);
  expect(bars("supply")).toHaveLength(4);
});

// Source: the brief (OP-1: the window whose anchor hour had no block says so, with no bar).
it("explains a window whose anchor hour had no block", async () => {
  show(blanked("7d", ALL_BANDS, ["7d"]));
  await screen.findByText(TITLE5);
  for (const chart of ["supply", "pnl"] as const) {
    expect(values(chart)).toEqual([MISSING, MISSING, MISSING, MISSING]);
    expect(rowNames(chart)).toEqual(GROUP_NAMES);
    expect(bars(chart)).toHaveLength(0);
    expect(panel(chart).querySelectorAll(".wh-sc-zero, .wh-sc-grid, .wh-seller-tick")).toHaveLength(
      0,
    );
    expect(legend(chart)).toEqual([MISSING, MISSING, MISSING]);
    expect(within(panel(chart)).getByText(NO_BLOCK)).toBeTruthy();
  }
  expect(screen.queryByText("No data for this chart")).toBeNull();
  for (const chart of ["supply", "pnl"] as const) {
    pick(chart, "Window", "1d");
    expect(within(panel(chart)).queryByText(/No block was mined/)).toBeNull();
    expect(bars(chart).length).toBeGreaterThan(0);
  }
  expect(values("supply")).toEqual(expected.supply[2].labels);
  expect(values("pnl")).toEqual(expected.pnl[4].labels);
});

// Source: the brief (no bar and no block note: the general "no data" line, still no zero).
it("says there is no data when no row has a value outside a no-block window", async () => {
  show(blanked("7d", ALL_BANDS));
  await screen.findByText(TITLE5);
  expect(within(panel("supply")).getByText("No data for this chart")).toBeTruthy();
  expect(within(panel("pnl")).getByText("No data for this chart")).toBeTruthy();
  expect(bars("supply")).toHaveLength(0);
  expect(values("supply")).toEqual([MISSING, MISSING, MISSING, MISSING]);
  expect(screen.queryByText(/No block was mined/)).toBeNull();
});

// Source: the brief (any control change clears the reading, as on the Sell side panels).
it("clears the reading when a control changes", async () => {
  show();
  await screen.findByText(TITLE5);
  key("supply", "ArrowDown");
  expect(readout("supply")).toContain("Large entities");
  pick("supply", "Breakdown", "Bands");
  expect(readout("supply")).toBe(HINT);
  expect(panel("supply").querySelectorAll(".wh-sc-hover")).toHaveLength(0);
  // The next key starts again from the top, in the new breakdown.
  key("supply", "ArrowDown");
  expect(readout("supply")).toContain("over 100k BTC");
  key("pnl", "End");
  expect(readout("pnl")).toContain("Retail");
  pick("pnl", "View", "Net");
  expect(readout("pnl")).toBe(HINT);
  key("pnl", "End");
  pick("pnl", "Window", "7d");
  expect(readout("pnl")).toBe(HINT);
});

// Source: Charts 3/4's rule (a reading names a row by its index, so new data drops it).
it("drops a reading when a refresh changes the data", async () => {
  const { client } = show();
  await screen.findByText(TITLE5);
  key("supply", "ArrowDown");
  // The same payload again keeps the reading.
  await poll(client, structuredClone(sample));
  expect(readout("supply")).toContain("Large entities");
  await poll(client, { ...structuredClone(sample), last_at: "2026-10-19T07:00:00Z" });
  expect(screen.getByText(/Data 2026-10-19 07:00 UTC/)).toBeTruthy();
  expect(readout("supply")).toBe(HINT);
});

// Source: the brief (the narrow layout: names above the bars, from the left edge).
it("puts the row names above the bars on a narrow chart", async () => {
  stubWidth(336);
  show();
  await screen.findByText(TITLE5);
  expect(svg("supply").getAttribute("data-compact")).toBe("true");
  expect(svg("supply").getAttribute("viewBox")).toBe("0 0 336 300");
  const names = [...panel("supply").querySelectorAll(".wh-sc-row")];
  const tops = [...bars("supply")].map((bar) => Number(bar.getAttribute("y")));
  names.forEach((name, i) => {
    // The brief's compact left margin is 56 and the name starts 4px in from the edge: 4 − 56.
    expect(name.getAttribute("x")).toBe("-52");
    expect(name.getAttribute("text-anchor")).toBe("start");
    expect(Number(name.getAttribute("y"))).toBeLessThan(tops[i]);
  });
  expect(texts("supply", ".wh-seller-tick")).toHaveLength(3);
  // The read row's shade takes in the gap above its bar, where its name is.
  key("supply", "ArrowDown");
  const shade = panel("supply").querySelector(".wh-sc-hover")!;
  const bar = bars("supply")[0];
  expect(num(shade, "y")).toBeLessThan(Number(names[0].getAttribute("y")) - 10);
  expect(num(shade, "y") + num(shade, "height")).toBeCloseTo(
    num(bar, "y") + num(bar, "height"),
    1,
  );
});

// Source: the brief (narrow layout: a row's name sits in the gap above its bar, and the read row's
// shade takes that gap in, so pointing at the name reads its row).
it("reads the row whose name the pointer is on in the narrow layout", async () => {
  stubWidth(336);
  show();
  await screen.findByText(TITLE5);
  pick("supply", "Breakdown", "Bands");
  const chart = svg("supply");
  // 336px, 12 rows: the compact chart is 12 × 26 + 42 = 354 tall, its plot 16px down.
  expect(chart.getAttribute("viewBox")).toBe("0 0 336 354");
  chart.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 336, height: 354, right: 336, bottom: 354 }) as DOMRect;
  const names = [...panel("supply").querySelectorAll(".wh-sc-row")];
  expect(names).toHaveLength(12);
  names.forEach((name) => {
    const baseline = 16 + Number(name.getAttribute("y"));
    // The upper half of the 10px name, then just above its baseline.
    for (const clientY of [baseline - 6, baseline - 1]) {
      fireEvent.pointerMove(chart, { clientX: 100, clientY, pointerType: "mouse" });
      expect(readout("supply").split(" · ")[0]).toBe(name.textContent);
    }
  });
});

it("says when the hour is forming", async () => {
  show();
  await screen.findByText(TITLE5);
  const meta = document.querySelector(".wh-seller-meta")!.textContent!;
  expect(meta).toContain("Data 2026-10-19 06:00 UTC");
  expect(meta).toContain("includes the forming hour");
  expect(screen.getByText("Rules: original v1")).toBeTruthy();
  expect(screen.queryByText(/Data is delayed/)).toBeNull();
});

it("warns when the data is delayed", async () => {
  show({ ...sample, data_state: "delayed" });
  await screen.findByText(TITLE5);
  expect(screen.getByText("Data is delayed · data to 2026-10-19 06:00 UTC")).toBeTruthy();
  const meta = document.querySelector(".wh-seller-meta")!.textContent!;
  expect(meta).toContain("last hour was partial when computed");
  expect(meta).not.toContain("includes the forming hour");
  expect(bars("supply")).toHaveLength(4);
  expect(bars("pnl")).toHaveLength(8);
});

it("warns when the data is stale", async () => {
  show({ ...sample, data_state: "stale", refreshing: true });
  await screen.findByText(TITLE5);
  expect(screen.getByText("Data is stale · data to 2026-10-19 06:00 UTC")).toBeTruthy();
  expect(document.querySelector(".wh-seller-meta")!.textContent).toContain(
    "last hour was partial when computed",
  );
  expect(screen.getByRole("status").textContent).toBe("Refreshing on-chain data…");
  expect(bars("supply")).toHaveLength(4);
});

it("invents no number while loading", async () => {
  const { container, unmount } = show("pending");
  expect(screen.getByText("Loading size cohorts…")).toBeTruthy();
  expect(container.textContent ?? "").not.toMatch(/\d/);
  unmount();

  show({
    ...sample,
    data_state: "unavailable",
    reasons: ["series_missing:hour1:addrs_over_100k_btc_supply"],
    forming_at: null,
    last_at: null,
    bands: [],
    refreshing: true,
  });
  expect(await screen.findByText("Size cohorts unavailable")).toBeTruthy();
  expect(screen.getByText("missing series hour1:addrs_over_100k_btc_supply")).toBeTruthy();
  expect(screen.getByRole("status").textContent).toBe("Refreshing on-chain data…");
  expect(document.querySelector("svg")).toBeNull();
  cleanup();

  show(new Error("Python service unavailable (HTTP 503). No simulated fallback was used."));
  expect(await screen.findByText("Size cohorts unavailable")).toBeTruthy();
  expect(screen.getByText(/HTTP 503/)).toBeTruthy();
  expect(document.querySelector("svg")).toBeNull();
});

it("puts the three notes under each chart", async () => {
  show();
  await screen.findByText(TITLE5);
  for (const chart of ["supply", "pnl"] as const) {
    const notes = panel(chart).querySelector(".wh-seller-read")!;
    expect([...notes.querySelectorAll("h4")].map((h) => h.textContent)).toEqual([
      "What it shows",
      "What extreme values imply",
      "How to read",
    ]);
    expect(notes.querySelectorAll("p")).toHaveLength(3);
  }
  expect(
    within(panel("supply")).getByText(/^How many coins each wallet-size band gained or lost/),
  ).toBeTruthy();
  expect(within(panel("pnl")).getByText(/^Dollars of profit and loss booked/)).toBeTruthy();
});

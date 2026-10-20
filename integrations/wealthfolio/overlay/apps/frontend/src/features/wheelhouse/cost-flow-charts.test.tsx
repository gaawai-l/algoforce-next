import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClustersTable, CostFlowCharts } from "./cost-flow-charts";
import { DEFAULT_SIDE, fitSide } from "./cost-flow-engine";
import {
  ALL_ON,
  ageLegend,
  ageRows,
  ageWeights,
  clusters,
  gridFor,
  labelX,
  plotFrame,
  sideWeights,
  udiff,
  type Side,
} from "./cost-flow";
import expected from "./cost-flow-expected.json";
import s1raw from "./cost-flow-sample-0512.json";
import s2raw from "./cost-flow-sample.json";
import { phrase, type TextFn } from "./i18n";
import { costFlowSchema, type CostFlowView } from "./onchain-contract";

const mocks = vi.hoisted(() => ({ costFlow: vi.fn() }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getCostFlow: mocks.costFlow,
}));
// The real engine, counted: hover, the keyboard readout and a resize must never reach it.
vi.mock("./cost-flow-engine", async (orig) => {
  const m = await orig<typeof import("./cost-flow-engine")>();
  return { ...m, fitSide: vi.fn(m.fitSide) };
});
const fits = vi.mocked(fitSide);

// requestAnimationFrame as a queue the tests drain by hand.
let frames = new Map<number, FrameRequestCallback>();
let lastFrame = 0;
const cancelFrame = vi.fn((id: number) => frames.delete(id));
beforeEach(() => {
  frames = new Map();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    lastFrame += 1;
    frames.set(lastFrame, callback);
    return lastFrame;
  });
  vi.stubGlobal("cancelAnimationFrame", cancelFrame);
});
const flush = () =>
  act(() => {
    const due = [...frames.values()];
    frames.clear();
    for (const callback of due) callback(0);
  });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

// S2: the 06:04 snapshot of 19 Oct 2026, the page's own snapshot; it has no $200 grid.
const s2 = costFlowSchema.parse(s2raw);
// S1: the 05:12 snapshot of the same day, taken before the age-cohort snapshots were in (age null).
const s1 = costFlowSchema.parse(s1raw);
const TITLE3 = "Chart 3 — Buy & Sell Side By Cost Basis";
const TITLE4 = "Chart 4 — Buy & Sell Side By Cost Basis · Age Breakdown";
// page-recorded (06:04): Chart 4's legend rows as "<label> / <value>", the Clusters meta and rows.
const PAGE4: Record<string, { legend: string[]; meta: string; clusters: string[] }> =
  expected.chart4_page;
// The plan's net label (N1, rule 4): the page wrote "net (issuance)" in every state.
const shownNet = (lines: readonly string[]) =>
  lines.map((line) => line.replace(/^net \(issuance\) \/ /, "net of what is shown / "));

function show(view: CostFlowView = s2) {
  mocks.costFlow.mockResolvedValue(view);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <CostFlowCharts />
      </QueryClientProvider>,
    ),
  };
}

// A poll's result, as the 5-minute refetch delivers it (observers hear of it on the next tick).
const poll = (client: QueryClient, view: CostFlowView) =>
  act(async () => {
    client.setQueryData(["wh", "onchain", "cost-flow"], view);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
const en: TextFn = (key, vars) => phrase("en", key, vars);

// The chart's width as useChartWidth reads it; `initial` is reported as soon as it is observed.
function stubWidth(initial?: number) {
  const fires: ((width: number) => void)[] = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private callback: ResizeObserverCallback) {}
      observe() {
        const fire = (width: number) =>
          this.callback(
            [{ contentRect: { width } } as ResizeObserverEntry],
            this as unknown as ResizeObserver,
          );
        fires.push(fire);
        if (initial) fire(initial);
      }
      disconnect() {}
    },
  );
  return (width: number) => act(() => fires.forEach((fire) => fire(width)));
}

const chart3 = () => document.querySelector<HTMLElement>('[data-chart="costflow-3"]')!;
const svg3 = () => chart3().querySelector<SVGSVGElement>("svg.wh-cf-svg");
const side = (which: Side) => chart3().querySelector<HTMLElement>(`[data-side="${which}"]`)!;
const pick = (scope: HTMLElement, group: string, name: string) =>
  fireEvent.click(
    within(within(scope).getByRole("group", { name: group })).getByRole("button", { name }),
  );
const buttons = (scope: HTMLElement, group: string) =>
  within(within(scope).getByRole("group", { name: group }))
    .getAllByRole("button")
    .map((button) => button.textContent);
const legend = () =>
  [...chart3().querySelectorAll(".wh-cf-legend .wh-seller-key")].map((key) => key.textContent);
const readout = (scope = chart3()) =>
  [...scope.querySelectorAll(".wh-cf-readout p")].map((line) => line.textContent);
const table = (name: "clusters" | "components", scope = chart3()) =>
  scope.querySelector<HTMLElement>(`[data-table="${name}"]`)!;
const tableRows = (name: "clusters" | "components", scope = chart3()) =>
  [...table(name, scope).querySelectorAll("tbody tr")].map((row) =>
    [...(row as HTMLTableRowElement).cells].map((cell) => cell.textContent),
  );
// The names of a control group's pressed buttons.
const pressed = (scope: HTMLElement, group: string) =>
  within(within(scope).getByRole("group", { name: group }))
    .getAllByRole("button")
    .filter((button) => button.getAttribute("aria-pressed") === "true")
    .map((button) => button.textContent);
const line = (cells: (string | null)[]) => cells.join(" | ");
const labels = (kind: "k" | "m", which: Side) =>
  [...svg3()!.querySelectorAll(`text.wh-cf-label--${kind}-${which}`)].map(
    (label) => label.textContent,
  );
const gear = (which: Side) => side(which).querySelector<HTMLButtonElement>(".wh-cf-gear")!;
const chip = (which: Side) => side(which).querySelector(".wh-cf-chip")!.textContent;
const slider = (which: Side, name: "width" | "peak cutoff") =>
  within(side(which)).getByRole<HTMLInputElement>("slider", { name });

// A path's points and a bar's edges, in the svg's units.
const points = (d: string) =>
  [...d.matchAll(/[ML]([\d.-]+),([\d.-]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
const edges = (rect: Element) => {
  const x = Number(rect.getAttribute("x"));
  const y = Number(rect.getAttribute("y"));
  return {
    left: x,
    right: x + Number(rect.getAttribute("width")),
    top: y,
    bottom: y + Number(rect.getAttribute("height")),
  };
};
const zeroX = () => Number(svg3()!.querySelector(".wh-cf-zero")!.getAttribute("x1"));

const chart4 = () => document.querySelector<HTMLElement>('[data-chart="costflow-4"]')!;
const svg4 = () => chart4().querySelector<SVGSVGElement>("svg.wh-cf-svg");
// Chart 4's legend in the page record's format, "<label> / <value>", and one of its rows by label.
const legend4 = () =>
  [...chart4().querySelectorAll(".wh-cf-legend .wh-seller-key")].map(
    (key) => `${key.querySelector("span")!.textContent} / ${key.querySelector("b")!.textContent}`,
  );
const legendRow = (label: string) =>
  [...chart4().querySelectorAll<HTMLElement>(".wh-cf-legend .wh-seller-key")].find(
    (key) => key.querySelector("span")!.textContent === label,
  )!;
const meta4 = () => table("clusters", chart4()).querySelector(".wh-cf-fit-meta")!.textContent;
// The bars of one legend row: a bought group's ("a<g>") or a sold band's ("s<band>").
const barsOf = (key: string) =>
  svg4()!.querySelectorAll(
    `.wh-cf-bar--${key[0] === "a" ? "bought" : "sold"}.wh-cf-age-${key.slice(1)}`,
  );
// The rows Chart 4 draws for a window and zoom of S2.
const rows4 = (w: "1d" | "7d" | "30d" | "90d", z: 0 | 50 | 25 | 10) => {
  const found = ageRows(s2, w, z);
  if (!found.ok) throw new Error(`no rows: ${found.missing}`);
  return found.value;
};
// How far a side reaches from zero: its widest bar, or its curves' farthest point.
const barReach = (which: Side) =>
  Math.max(
    ...[...svg3()!.querySelectorAll(`.wh-cf-bar--${which}`)].map((bar) =>
      which === "pos" ? edges(bar).right - zeroX() : zeroX() - edges(bar).left,
    ),
  );
const curveReach = (kind: "kde" | "mix", which: Side) =>
  Math.max(
    ...[...svg3()!.querySelectorAll(`path.wh-cf-${kind}--${which}`)].flatMap((path) =>
      points(path.getAttribute("d")!).map(([x]) => (which === "pos" ? x - zeroX() : zeroX() - x)),
    ),
  );

// The rows and the sell side's weights of 30d All Zoom All, as the chart draws them.
const defaultRows = () => {
  const found = udiff(gridFor(s2, "all")!, "30d", "all", false, 0, s2.spot!);
  if (!found.ok) throw new Error("no rows");
  return found.value;
};

it("plotFrame keeps the plot and the spot label inside 330 px", async () => {
  const f = plotFrame(330);
  expect(f).toEqual({
    left: 44,
    right: 76,
    top: 8,
    bottom: 34,
    plotW: 210,
    xTicks: 3,
    yTicks: 6,
    labelPx: 10,
    spotX: 328,
  });
  expect(f.plotW).toBeGreaterThanOrEqual(200);
  expect(f.left + f.plotW).toBeLessThan(f.spotX);
  expect(f.spotX).toBeLessThanOrEqual(330);
  expect(plotFrame(1100)).toEqual({
    left: 64,
    right: 96,
    top: 10,
    bottom: 36,
    plotW: 940,
    xTicks: 7,
    yTicks: 10,
    labelPx: 11,
    spotX: 1098,
  });
  // The wide frame starts at 500 px.
  expect(plotFrame(499).left).toBe(44);
  expect(plotFrame(500).left).toBe(64);
  // Drawn at 330 px: 300 px high (the floor of the height), the spot label right-aligned in the
  // right margin, and every tick label inside the chart.
  stubWidth(330);
  show();
  await screen.findByText(TITLE3);
  expect(svg3()!.getAttribute("viewBox")).toBe("0 0 330 300");
  const spot = svg3()!.querySelector("text.wh-cf-spot")!;
  expect(spot.getAttribute("x")).toBe("328");
  expect(spot.getAttribute("text-anchor")).toBe("end");
  const xTicks = [...svg3()!.querySelectorAll("text.wh-cf-tick--x")];
  expect(xTicks.length).toBeGreaterThanOrEqual(2);
  expect(xTicks.length).toBeLessThanOrEqual(5);
  for (const tick of xTicks) {
    const x = Number(tick.getAttribute("x"));
    expect(x).toBeGreaterThanOrEqual(f.left);
    expect(x).toBeLessThanOrEqual(f.left + f.plotW);
  }
  for (const tick of svg3()!.querySelectorAll("text.wh-cf-tick--y"))
    expect(Number(tick.getAttribute("x"))).toBe(f.left - 6);
});

it("labelX keeps K and M labels inside the plot", async () => {
  const f = plotFrame(330);
  expect(labelX(46, "neg", f)).toBe(63);
  expect(labelX(250, "pos", f)).toBe(235);
  // Away from the edges a label sits 8 px off its point.
  expect(labelX(150, "neg", f)).toBe(142);
  expect(labelX(150, "pos", f)).toBe(158);
  // 11 px labels are ceil(3 × 0.62 × 11) = 21 px wide.
  const wide = plotFrame(1100);
  expect(labelX(70, "neg", wide)).toBe(85);
  expect(labelX(1000, "pos", wide)).toBe(983);
  // Drawn at 330 px with the bells on: every K and M label stays between the plot's edges.
  stubWidth(330);
  show();
  await screen.findByText(TITLE3);
  pick(side("pos"), "Bell curves", "On");
  pick(side("neg"), "Bell curves", "On");
  const drawn = [...svg3()!.querySelectorAll("text.wh-cf-label")];
  expect(drawn.map((label) => label.textContent).sort()).toEqual(
    ["K1", "K2", "K3", "K4", "K5", "M1", "M1", "M2", "M3", "M4"].sort(),
  );
  let clamped = 0;
  for (const label of drawn) {
    const x = Number(label.getAttribute("x"));
    expect(label.getAttribute("font-size")).toBe("10");
    if (label.getAttribute("text-anchor") === "end") {
      expect(x - 19).toBeGreaterThanOrEqual(f.left);
      expect(x).toBeLessThanOrEqual(f.left + f.plotW);
      if (x === f.left + 19) clamped += 1;
    } else {
      expect(label.getAttribute("text-anchor")).toBe("start");
      expect(x).toBeGreaterThanOrEqual(f.left);
      expect(x + 19).toBeLessThanOrEqual(f.left + f.plotW);
      if (x === f.left + f.plotW - 19) clamped += 1;
    }
  }
  // The tallest peaks sit near the plot's edges, so some labels are pulled in.
  expect(clamped).toBeGreaterThan(0);
});

it("never calls the engine for hover or the keyboard readout", async () => {
  const resize = stubWidth();
  show();
  await screen.findByText(TITLE3);
  // One fit per side of each chart on the first render.
  const count = fits.mock.calls.length;
  expect(count).toBe(4);
  const svg = svg3()!;
  // 720 wide by default and 440 high.
  svg.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 720, height: 440, right: 720, bottom: 440 }) as DOMRect;
  const read = new Set<string | null>();
  for (let i = 0; i < 20; i += 1) {
    fireEvent.pointerMove(svg, { clientX: 300, clientY: 40 + i * 8, pointerType: "mouse" });
    read.add(readout()[0]);
  }
  // Every move reads another bucket.
  expect(read.size).toBe(20);
  expect(fits.mock.calls.length).toBe(count);
  fireEvent.pointerLeave(svg, { pointerType: "mouse" });
  expect(readout()).toEqual([]);
  for (let i = 0; i < 20; i += 1) {
    fireEvent.keyDown(svg, { key: "ArrowUp" });
    read.add(readout()[0]);
  }
  expect(read.size).toBeGreaterThan(20);
  expect(fits.mock.calls.length).toBe(count);
  resize(330);
  expect(svg.getAttribute("viewBox")).toBe("0 0 330 300");
  expect(fits.mock.calls.length).toBe(count);
});

it("coalesces ten slider inputs into one recompute", async () => {
  const { unmount } = show();
  await screen.findByText(TITLE3);
  pick(side("neg"), "Smoothing", "Manual");
  fireEvent.click(gear("neg"));
  const cutoff = slider("neg", "peak cutoff");
  const before = fits.mock.calls.length;
  const values = Array.from({ length: 10 }, (_, i) => (6 + i) / 100);
  for (const value of values) fireEvent.input(cutoff, { target: { value: String(value) } });
  // Nothing is fitted until the frame runs, but the slider already reads the last value.
  expect(fits.mock.calls.length).toBe(before);
  expect(cutoff.value).toBe("0.15");
  expect(side("neg").querySelector(`output[for="${cutoff.id}"]`)!.textContent).toBe("0.15");
  expect(frames.size).toBe(1);
  const timed = performance.getEntriesByName("costflow-fit").length;
  flush();
  expect(fits.mock.calls.length).toBe(before + 1);
  const [centers, weights, setting] = fits.mock.calls[before];
  const rows = defaultRows();
  expect(centers).toEqual(rows.map((row) => row.price));
  expect(weights).toEqual(sideWeights(rows, "all", false, "neg"));
  expect(setting).toEqual({ ...DEFAULT_SIDE, smoothing: "kde", minProm: 0.15 });
  // The fit is timed for the browser check.
  expect(performance.getEntriesByName("costflow-fit").length).toBe(timed + 1);
  expect(chip("neg")).toBe("0.020 / 0.15");
  // A frame still pending when the chart goes away is cancelled.
  fireEvent.input(cutoff, { target: { value: "0.2" } });
  expect(frames.size).toBe(1);
  const [pending] = frames.keys();
  unmount();
  expect(cancelFrame).toHaveBeenCalledWith(pending);
  expect(frames.size).toBe(0);
});

it("draws Chart 3 with the original's default readings", async () => {
  show();
  await screen.findByText(TITLE3);
  // page-recorded (05:55 sweep, "30d all zoomAll" and "restored defaults", the S2 snapshot).
  expect(legend()).toEqual([
    "Net Buy (Accumulation) +1,134,837 BTC",
    "Net Sell (Distribution) −1,121,241 BTC",
  ]);
  expect(svg3()!.getAttribute("data-rows")).toBe("252");
  expect(svg3()!.querySelectorAll(".wh-cf-bar--pos")).toHaveLength(12);
  expect(svg3()!.querySelectorAll(".wh-cf-bar--neg")).toHaveLength(240);
  expect(svg3()!.querySelectorAll(".wh-cf-bar--aging-pos, .wh-cf-bar--aging-neg")).toHaveLength(
    0,
  );
  expect(table("clusters").querySelector(".wh-cf-fit-meta")!.textContent).toBe(
    "5 clusters · 1 in · 4 out",
  );
  expect(tableRows("clusters").map(line)).toEqual([
    "K1 | Net Sell (Distribution) | $41,750 | $6,768 | 34,546 BTC | 3.1% | 7% | 49.3% below",
    "K2 | Net Sell (Distribution) | $63,750 | $8,413 | 258,016 BTC | 23.0% | 30% | 22.6% below",
    "K3 | Net Sell (Distribution) | $77,750 | $6,960 | 490,118 BTC | 43.7% | 99% | 5.6% below",
    "K4 | Net Buy (Accumulation) | $83,750 | $6,773 | 1,134,837 BTC | 100.0% | 100% | 1.7% above",
    "K5 | Net Sell (Distribution) | $91,250 | $41,110 | 668,265 BTC | 59.6% | 7% | 10.8% above",
  ]);
  // The vs-spot tag: support below spot, resistance above.
  const tags = [...table("clusters").querySelectorAll(".wh-cf-tag")].map((tag) =>
    tag.classList.contains("wh-cf-tag--support") ? "support" : "resistance",
  );
  expect(tags).toEqual(["support", "support", "support", "resistance", "resistance"]);
  expect(tableRows("components")).toEqual([
    ["Bell curves are off. Turn them on for either side above."],
  ]);
  expect(table("components").querySelector(".wh-cf-fit-meta")!.textContent).toBe("");
  // The chart numbers its K marks as the table does (U4).
  expect(labels("k", "pos")).toEqual(["K4"]);
  expect(labels("k", "neg")).toEqual(["K1", "K2", "K3", "K5"]);
  expect(svg3()!.querySelectorAll("path.wh-cf-kde")).toHaveLength(2);
  expect(svg3()!.querySelectorAll("path.wh-cf-mix")).toHaveLength(0);
  // A:1694-1696: each side's KDE peaks at 92% of its tallest bar (one bar per row for All).
  for (const which of ["pos", "neg"] as const)
    expect(curveReach("kde", which) / barReach(which)).toBeCloseTo(0.92, 2);
  expect(svg3()!.querySelector("text.wh-cf-spot")!.textContent).toBe("spot $82,361");
  expect(chart3().querySelector(".wh-cf-captions")!.textContent).toBe(
    "BTC ← Net Sell (Distribution)Net Buy (Accumulation) → BTC",
  );
  expect(chart3().querySelector(".wh-cf-note")!.textContent).toBe(
    "All-cohort diff nets aging out by construction, so this toggle changes nothing here. $500 bins.",
  );
  // The defaults: 30d, All, Zoom All, Aging Hide; both sides Auto, Bells Off, How many auto.
  for (const [group, name] of [
    ["Window", "30d"],
    ["Holders", "All"],
    ["Zoom", "All"],
    ["Aging", "Hide"],
  ])
    expect(
      within(within(chart3()).getByRole("group", { name: group }))
        .getByRole("button", { name })
        .getAttribute("aria-pressed"),
    ).toBe("true");
  for (const which of ["pos", "neg"] as const) {
    expect(chip(which)).toBe("auto");
    expect(buttons(side(which), "How many")).toEqual(["auto", "1", "2", "3", "4", "5"]);
  }
  // page-recorded ("1d all zoomAll"): a bucket that did not change draws no bar.
  pick(chart3(), "Window", "1d");
  expect(legend()).toEqual([
    "Net Buy (Accumulation) +54,914 BTC",
    "Net Sell (Distribution) −54,811 BTC",
  ]);
  expect(svg3()!.querySelectorAll(".wh-cf-bar--pos")).toHaveLength(1);
  expect(svg3()!.querySelectorAll(".wh-cf-bar--neg")).toHaveLength(247);
  const oneDay = udiff(gridFor(s2, "all")!, "1d", "all", false, 0, s2.spot!);
  expect(oneDay.ok && oneDay.value.length).toBeGreaterThan(248);
  expect(svg3()!.getAttribute("data-rows")).toBe(String(oneDay.ok && oneDay.value.length));
});

it("draws no vs-spot tag without a spot", () => {
  const rows = defaultRows();
  const pos = fitSide(
    rows.map((row) => row.price),
    sideWeights(rows, "all", false, "pos"),
    DEFAULT_SIDE,
  );
  render(<ClustersTable rows={clusters(pos, null)} spot={0} empty="none" />);
  const cells = [...document.querySelectorAll("tbody tr td, tbody tr th")].map(
    (cell) => cell.textContent,
  );
  expect(cells.at(-1)).toBe("—");
  expect(document.querySelector(".wh-cf-tag")).toBeNull();
});

it("fits bell curves on request", async () => {
  show();
  await screen.findByText(TITLE3);
  pick(side("pos"), "Bell curves", "On");
  pick(side("neg"), "Bell curves", "On");
  // page-recorded (05:55 sweep, "30d all zoomAll aging off bells on").
  expect(table("components").querySelector(".wh-cf-fit-meta")!.textContent).toBe(
    "in: 1 bell · out: 4 bells",
  );
  expect(tableRows("components").map(line)).toEqual([
    "M1 | Net Sell (Distribution) | $26,743 | $16,723 | 7.9% | 88,021 BTC | 67.5% below",
    "M2 | Net Sell (Distribution) | $63,489 | $1,764 | 19.8% | 222,267 BTC | 22.9% below",
    "M3 | Net Sell (Distribution) | $77,733 | $1,248 | 40.0% | 447,953 BTC | 5.6% below",
    "M1 | Net Buy (Accumulation) | $83,663 | $1,363 | 100.0% | 1,134,837 BTC | 1.6% above",
    "M4 | Net Sell (Distribution) | $83,835 | $20,236 | 32.4% | 362,999 BTC | 1.8% above",
  ]);
  expect(buttons(side("pos"), "How many")[0]).toBe("auto · 1");
  expect(buttons(side("neg"), "How many")[0]).toBe("auto · 4");
  expect(labels("m", "pos")).toEqual(["M1"]);
  expect(labels("m", "neg")).toEqual(["M1", "M2", "M3", "M4"]);
  expect(svg3()!.querySelectorAll("path.wh-cf-mix--pos")).toHaveLength(1);
  expect(svg3()!.querySelectorAll("path.wh-cf-mix--neg")).toHaveLength(4);
  // A:1728-1730: a side's bells together peak at 85% of its tallest bar.
  for (const which of ["pos", "neg"] as const)
    expect(curveReach("mix", which) / barReach(which)).toBeCloseTo(0.85, 2);
  // The clusters do not depend on the bells.
  expect(tableRows("clusters")).toHaveLength(5);
  // A manual k: three bells on the sell side, and auto reads plain "auto" again.
  pick(side("neg"), "How many", "3");
  expect(labels("m", "neg")).toEqual(["M1", "M2", "M3"]);
  expect(buttons(side("neg"), "How many")[0]).toBe("auto");
  expect(table("components").querySelector(".wh-cf-fit-meta")!.textContent).toBe(
    "in: 1 bell · out: 3 bells",
  );
});

it("tunes a side by hand", async () => {
  show();
  await screen.findByText(TITLE3);
  pick(side("neg"), "Smoothing", "Manual");
  expect(chip("neg")).toBe("0.020 / 0.05");
  fireEvent.click(gear("neg"));
  expect(gear("neg").getAttribute("aria-expanded")).toBe("true");
  const width = slider("neg", "width");
  const cutoff = slider("neg", "peak cutoff");
  for (const [input, min, max, step, value] of [
    [width, "0.005", "0.10", "0.001", "0.02"],
    [cutoff, "0.01", "0.40", "0.005", "0.05"],
  ] as const) {
    expect(input.disabled).toBe(false);
    expect(input.getAttribute("min")).toBe(min);
    expect(input.getAttribute("max")).toBe(max);
    expect(input.getAttribute("step")).toBe(step);
    expect(input.value).toBe(value);
  }
  // The frame commits onto the setting current when it runs: Bells On, picked while the cutoff
  // waits for its frame, stays on.
  fireEvent.input(cutoff, { target: { value: "0.40" } });
  pick(side("neg"), "Bell curves", "On");
  flush();
  expect(chip("neg")).toBe("0.020 / 0.40");
  expect(
    tableRows("components").filter((row) => row[1] === "Net Sell (Distribution)").length,
  ).toBeGreaterThan(0);
  // derived from page values: only the sell peak of strength 99% (K3) clears a 0.40 cutoff.
  const sells = tableRows("clusters").filter((row) => row[1] === "Net Sell (Distribution)");
  expect(sells).toHaveLength(1);
  expect(sells[0][2]).toBe("$77,750");
  expect(chip("neg")).toBe("0.020 / 0.40");
  // The buy side is untouched.
  expect(tableRows("clusters").filter((row) => row[1] === "Net Buy (Accumulation)")).toHaveLength(
    1,
  );
  // A value still waiting for its frame when the side leaves Manual is dropped, not committed
  // onto Auto.
  fireEvent.input(cutoff, { target: { value: "0.30" } });
  expect(frames.size).toBe(1);
  pick(side("neg"), "Smoothing", "Auto");
  flush();
  expect(chip("neg")).toBe("auto");
  for (const [input, value] of [
    [width, "0.02"],
    [cutoff, "0.05"],
  ] as const) {
    expect(input.disabled).toBe(true);
    expect(input.value).toBe(value);
    expect(side("neg").querySelector(`output[for="${input.id}"]`)!.textContent).toBe("auto");
  }
  expect(tableRows("clusters")).toHaveLength(5);
  // Off draws no curve on that side: no peaks, so its clusters go.
  pick(side("neg"), "Smoothing", "Off");
  expect(chip("neg")).toBe("raw");
  expect(tableRows("clusters").map((row) => row[0])).toEqual(["K1"]);
  expect(svg3()!.querySelectorAll("path.wh-cf-kde--neg")).toHaveLength(0);
});

it("shows the aging split for LTH", async () => {
  show();
  await screen.findByText(TITLE3);
  pick(chart3(), "Window", "90d");
  pick(chart3(), "Holders", "LTH");
  pick(chart3(), "Aging", "Show");
  pick(side("neg"), "Bell curves", "On");
  // page-recorded (05:55 sweep, "90d lth zoomAll aging on bells on").
  expect(legend()).toEqual([
    "Net Buy (Accumulation) +3,210,656 BTC",
    "Net Sell (Distribution) −1,886,531 BTC",
    "Aging STH→LTH 1,283,400 BTC · 40% of buy side",
  ]);
  // The aging row is drawn hollow, on the side it sits on.
  const swatches = [...chart3().querySelectorAll(".wh-cf-legend .wh-seller-swatch")];
  expect(swatches[2].className).toContain("wh-cf-swatch--pos");
  expect(swatches[2].className).toContain("wh-cf-swatch--hollow");
  expect(swatches[0].className).not.toContain("wh-cf-swatch--hollow");
  expect(svg3()!.querySelectorAll(".wh-cf-bar--pos")).toHaveLength(28);
  expect(svg3()!.querySelectorAll(".wh-cf-bar--neg")).toHaveLength(224);
  expect(svg3()!.querySelectorAll(".wh-cf-bar--aging-pos")).toHaveLength(35);
  // The axis spans ±1.08 × the widest stack, aging included (A:1592-1600): every bar stays in
  // the plot, and the widest stack reaches 1/1.08 of the way to its edge.
  const f = plotFrame(720);
  const bars = [...svg3()!.querySelectorAll(".wh-cf-bar")].map(edges);
  for (const bar of bars) {
    expect(bar.left).toBeGreaterThanOrEqual(f.left);
    expect(bar.right).toBeLessThanOrEqual(f.left + f.plotW);
  }
  const widest = Math.max(
    ...bars.map((bar) => Math.max(bar.right - zeroX(), zeroX() - bar.left)),
  );
  expect(widest).toBeCloseTo(f.plotW / 2 / 1.08, 0);
  expect(table("clusters").querySelector(".wh-cf-fit-meta")!.textContent).toBe(
    "7 clusters · 1 in · 6 out",
  );
  expect(buttons(side("neg"), "How many")[0]).toBe("auto · 5 of 6");
  expect(chart3().querySelector(".wh-cf-note")!.textContent).toBe(
    "Real LTH buying and selling, plus the coins that arrived by ageing — both on the buy side. Aging is a lower bound. $500 bins.",
  );
  expect(chart3().querySelector(".wh-cf-span")!.textContent).toBe(
    "90d · 21 Jul close → 19 Oct 06:04 UTC",
  );
});

it("says a window is missing instead of drawing zeros", async () => {
  const view = structuredClone(s2);
  view.grids[0].windows = view.grids[0].windows.filter((found) => found.window !== "1d");
  show(view);
  await screen.findByText(TITLE3);
  pick(chart3(), "Window", "1d");
  expect(
    within(chart3()).getByText("No 1d comparison: a snapshot it needs is missing."),
  ).toBeTruthy();
  expect(svg3()).toBeNull();
  // Nothing that would read as a number: no legend, span, readout or tables.
  for (const part of [".wh-cf-legend", ".wh-cf-span", ".wh-cf-readout", "[data-table]"])
    expect(chart3().querySelector(part)).toBeNull();
  // Chart 4 shares the window and says the same.
  expect(
    within(chart4()).getByText("No 1d comparison: a snapshot it needs is missing."),
  ).toBeTruthy();
  expect(svg4()).toBeNull();
  for (const part of [".wh-cf-legend", ".wh-cf-span", ".wh-cf-readout", "[data-table]"])
    expect(chart4().querySelector(part)).toBeNull();
  // The controls stay, so another window can be chosen.
  pick(chart3(), "Window", "7d");
  expect(svg3()).not.toBeNull();
  expect(chart3().querySelector(".wh-cf-span")!.textContent).toBe(
    "7d · 12 Oct close → 19 Oct 06:04 UTC",
  );
  expect(svg4()).not.toBeNull();
  expect(chart4().querySelector(".wh-cf-span")!.textContent).toBe(
    "7d · 12 Oct close → 19 Oct 06:04 UTC",
  );
  expect(screen.queryByText(/No 1d comparison/)).toBeNull();
  // Chart 4's own window buttons reach the missing window too.
  pick(chart4(), "Window", "1d");
  expect(pressed(chart3(), "Window")).toEqual(["1d"]);
  expect(svg3()).toBeNull();
  expect(svg4()).toBeNull();
});

it("says the $200 grid is missing", async () => {
  show();
  await screen.findByText(TITLE3);
  pick(chart3(), "Holders", "STH");
  expect(within(chart3()).getByText("STH needs the $200 snapshots, which are missing.")).toBeTruthy();
  expect(svg3()).toBeNull();
  expect(chart3().querySelector(".wh-cf-legend")).toBeNull();
  // The header names what is missing.
  expect(
    screen.getByText(
      "All-holder URPD snapshot missing for the $200 bucket · STH URPD snapshot missing for the $200 bucket · LTH URPD snapshot missing for the $200 bucket",
    ),
  ).toBeTruthy();
  expect(screen.getByText("Rules: original v1")).toBeTruthy();
  pick(chart3(), "Holders", "All");
  expect(svg3()!.getAttribute("data-rows")).toBe("252");
});

it("reads a bucket with the keyboard", async () => {
  show();
  await screen.findByText(TITLE3);
  const svg = svg3()!;
  expect(chart3().querySelector(".wh-cf-readout")!.getAttribute("aria-live")).toBe("polite");
  fireEvent.focus(svg);
  fireEvent.keyDown(svg, { key: "ArrowUp" });
  // page-recorded tooltip format; the first key reads the bucket that holds spot.
  expect(readout()).toEqual([
    "$82,000 – $82,500",
    "Real net flow +220,010",
    "LTH distribution +13,621",
    "STH apparent +233,631",
    "STH acquired at this cost basis · 30d window",
  ]);
  expect(svg.querySelector(".wh-cf-cursor")).not.toBeNull();
  fireEvent.keyDown(svg, { key: "ArrowUp" });
  expect(readout()[0]).toBe("$82,500 – $83,000");
  fireEvent.keyDown(svg, { key: "ArrowDown" });
  fireEvent.keyDown(svg, { key: "ArrowDown" });
  expect(readout()[0]).toBe("$81,500 – $82,000");
  fireEvent.keyDown(svg, { key: "Home" });
  expect(readout()[0]).toBe("$0 – $500");
  fireEvent.keyDown(svg, { key: "ArrowDown" });
  expect(readout()[0]).toBe("$0 – $500");
  fireEvent.keyDown(svg, { key: "End" });
  expect(readout()[0]).toBe("$125,500 – $126,000");
  fireEvent.keyDown(svg, { key: "Escape" });
  expect(readout()).toEqual([]);
  expect(svg.querySelector(".wh-cf-cursor")).toBeNull();
  // A new window clears the reading.
  fireEvent.keyDown(svg, { key: "ArrowDown" });
  expect(readout()).toHaveLength(5);
  pick(chart3(), "Window", "7d");
  expect(readout()).toEqual([]);
  // So do the holders, whose rows replace these.
  fireEvent.keyDown(svg3()!, { key: "ArrowDown" });
  expect(readout()).toHaveLength(5);
  pick(chart3(), "Holders", "LTH");
  expect(readout()).toEqual([]);
});

it("spans the BTC axis by the widest stack, not the net", async () => {
  // Hand-built from S2: at $60,000–$60,500 over 30d, 3M BTC leave All while 3M leave STH by
  // ageing. LTH with Aging Show draws a −3M real bar and a +3M aging bar on that row: the stack
  // is 3M each way while the row's net is 0.
  const view = structuredClone(s2);
  const grid = view.grids[0];
  const i = grid.floors.indexOf(60_000);
  const then = grid.windows.find((found) => found.window === "30d")!.then;
  then.all[i] = grid.now.all[i] + 3_000_000;
  then.sth[i] = grid.now.sth[i] + 3_000_000;
  then.lth[i] = grid.now.lth[i];
  show(view);
  await screen.findByText(TITLE3);
  pick(chart3(), "Holders", "LTH");
  pick(chart3(), "Aging", "Show");
  const f = plotFrame(720);
  const bars = [...svg3()!.querySelectorAll(".wh-cf-bar")].map(edges);
  for (const bar of bars) {
    expect(bar.left).toBeGreaterThanOrEqual(f.left);
    expect(bar.right).toBeLessThanOrEqual(f.left + f.plotW);
  }
  // ±1.08 × 3M: the row's two bars reach 1/1.08 of the way to each edge.
  expect(zeroX() - Math.min(...bars.map((bar) => bar.left))).toBeCloseTo(f.plotW / 2 / 1.08, 0);
  expect(Math.max(...bars.map((bar) => bar.right)) - zeroX()).toBeCloseTo(f.plotW / 2 / 1.08, 0);
});

it("pads Zoom All and not a ±% zoom", async () => {
  show();
  await screen.findByText(TITLE3);
  const f = plotFrame(720);
  const plotH = 440 - f.top - f.bottom;
  const span = () => {
    const bars = [...svg3()!.querySelectorAll(".wh-cf-bar")].map(edges);
    return [Math.min(...bars.map((bar) => bar.top)), Math.max(...bars.map((bar) => bar.bottom))];
  };
  // Zoom All: 252 rows from $0 to $126,000, padded by 5% above; never below $0.
  const [top, bottom] = span();
  expect(bottom).toBeCloseTo(f.top + plotH, 0);
  expect(top - f.top).toBeCloseTo((plotH * 0.05 * 126_000) / (126_000 * 1.05), 0);
  // ±10%: the band itself, rows edge to edge.
  pick(chart3(), "Zoom", "±10%");
  const rows = Number(svg3()!.getAttribute("data-rows"));
  expect(rows).toBe(33);
  const [zTop, zBottom] = span();
  const half = plotH / rows / 2;
  expect(zTop - f.top).toBeCloseTo(half - (half * 2 - 1) / 2, 0);
  expect(f.top + plotH - zBottom).toBeCloseTo(half - (half * 2 - 1) / 2, 0);
});

it("puts the three explanations under Chart 3", async () => {
  show();
  await screen.findByText(TITLE3);
  const read = chart3().querySelector(".wh-seller-read")!;
  // Last in the panel, after the tables.
  expect(chart3().lastElementChild).toBe(read);
  expect([...read.querySelectorAll("h4")].map((heading) => heading.textContent)).toEqual([
    "What it shows",
    "What extreme values imply",
    "How to read",
  ]);
  const bodies = [...read.querySelectorAll("p")].map((body) => body.textContent ?? "");
  expect(bodies[0].startsWith("Where supply changed hands over the window, by cost basis.")).toBe(
    true,
  );
  expect(
    bodies[1].startsWith("A large Net Buy cluster at spot is a fresh cost base:"),
  ).toBe(true);
  expect(bodies[2].startsWith("Price runs up the vertical axis and BTC across:")).toBe(true);
});

it("marks the forming snapshot by its day", async () => {
  show();
  await screen.findByText(TITLE3);
  expect(
    screen.getByText("URPD snapshot 19 Oct 2026 · 06:04 UTC · Source Bitcoin Research Kit"),
  ).toBeTruthy();
  expect(screen.getByText("includes the forming snapshot of 19 Oct 2026")).toBeTruthy();
  expect(chart3().querySelector(".wh-cf-span")!.textContent).toBe(
    "30d · 19 Sep close → 19 Oct 06:04 UTC",
  );
  cleanup();
  show({ ...s2, forming_at: null });
  await screen.findByText(TITLE3);
  expect(chart3().querySelector(".wh-cf-span")!.textContent).toBe("30d · 19 Sep close → 19 Oct close");
  expect(screen.queryByText(/forming snapshot/)).toBeNull();
});

// At 00:12 BRK may not have the new day's snapshot yet, so D is the day before, fetched closed.
it("dates the header by the snapshot day, not the day it was fetched", async () => {
  show({ ...s1, snapshot_at: "2026-10-20T00:12:00Z", forming_at: null });
  await screen.findByText(TITLE3);
  const header = document.querySelector(".wh-costflow > .wh-seller-meta")!;
  expect(header.textContent).toBe("URPD snapshot 19 Oct 2026 close · Source Bitcoin Research Kit");
  expect(chart3().querySelector(".wh-cf-span")!.textContent).toBe("30d · 19 Sep close → 19 Oct close");
});

it("warns when the snapshot is out of date or fails QC", async () => {
  show({
    ...s2,
    data_state: "stale",
    qc: ["cohort_sum:lin500", "sold_negative:30d", "age_floor", "new_check"],
  });
  await screen.findByText(TITLE3);
  expect(screen.getByText("Snapshot out of date · 19 Oct 2026")).toBeTruthy();
  expect(
    screen.getByText(
      "QC failed: STH + LTH ≠ All at $500, sold below zero in 30d, age floor contradicted, new_check",
    ),
  ).toBeTruthy();
  // QC only warns; the chart is drawn.
  expect(svg3()).not.toBeNull();
});

it("says the flows are unavailable without inventing numbers", async () => {
  show({
    ...s2,
    data_state: "unavailable",
    reasons: ["brk_unavailable"],
    grids: [],
    age: null,
    spot: null,
    now_day: null,
    snapshot_at: null,
    forming_at: null,
  });
  expect(await screen.findByText("Cost-basis flows unavailable")).toBeTruthy();
  expect(screen.getByText("on-chain data source unavailable")).toBeTruthy();
  expect(document.querySelector('[data-chart="costflow-3"]')).toBeNull();
  expect(document.querySelector('[data-chart="costflow-4"]')).toBeNull();
  cleanup();
  mocks.costFlow.mockReturnValue(new Promise(() => {}));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={client}>
      <CostFlowCharts />
    </QueryClientProvider>,
  );
  expect(screen.getByText("Loading the cost-basis flows…")).toBeTruthy();
  expect(container.textContent ?? "").not.toMatch(/\d/);
});

it("does not refit when an option already on is picked again", async () => {
  show();
  await screen.findByText(TITLE3);
  const count = fits.mock.calls.length;
  // Each pick makes a new setting object with the same six values.
  pick(side("neg"), "Smoothing", "Auto");
  pick(side("neg"), "Bell curves", "Off");
  pick(side("neg"), "How many", "auto");
  pick(side("pos"), "Smoothing", "Auto");
  expect(fits.mock.calls.length).toBe(count);
  pick(side("neg"), "Bell curves", "On");
  expect(fits.mock.calls.length).toBe(count + 1);
  pick(side("neg"), "Bell curves", "On");
  expect(fits.mock.calls.length).toBe(count + 1);
});

it("drops a reading when a refresh changes the rows", async () => {
  const { client } = show();
  await screen.findByText(TITLE4);
  fireEvent.keyDown(svg3()!, { key: "ArrowUp" });
  fireEvent.keyDown(svg4()!, { key: "ArrowUp" });
  expect(readout()).toHaveLength(5);
  expect(readout(chart4())).toHaveLength(7);
  // The same payload again keeps the view, its rows and so both readings.
  await poll(client, structuredClone(s2));
  expect(client.getQueryData(["wh", "onchain", "cost-flow"])).toBe(s2);
  expect(readout()).toHaveLength(5);
  expect(readout(chart4())).toHaveLength(7);
  // The next snapshot: the rows are new, and the readings, which name a row by its index, go.
  const next = structuredClone(s2);
  next.snapshot_at = "2026-10-19T07:04:42Z";
  await poll(client, next);
  expect(
    screen.getByText("URPD snapshot 19 Oct 2026 · 07:04 UTC · Source Bitcoin Research Kit"),
  ).toBeTruthy();
  expect(readout()).toEqual([]);
  expect(readout(chart4())).toEqual([]);
  expect(svg3()!.querySelector(".wh-cf-cursor")).toBeNull();
  expect(svg4()!.querySelector(".wh-cf-cursor")).toBeNull();
  // The next key starts again from the row that holds spot.
  fireEvent.keyDown(svg3()!, { key: "ArrowUp" });
  expect(readout()[0]).toBe("$82,000 – $82,500");
});

// Chart 4, the Age Breakdown, under Chart 3 on the same S2 snapshot.
describe("Chart 4", () => {
  it("says what is missing in Chart 4", async () => {
    // Review Focus 2: S1 has no age-cohort snapshots; Chart 4 says so and draws nothing.
    show(s1);
    await screen.findByText(TITLE4);
    expect(
      within(chart4()).getByText(
        "Chart 4 needs the age-cohort snapshots and the daily high and low for 19 Oct 2026, which are missing or from another block.",
      ),
    ).toBeTruthy();
    expect(svg4()).toBeNull();
    for (const part of [".wh-cf-legend", ".wh-cf-span", ".wh-cf-readout", ".wh-cf-sides", "[data-table]"])
      expect(chart4().querySelector(part)).toBeNull();
    // Its controls stay; Chart 3 draws.
    expect(pressed(chart4(), "Window")).toEqual(["30d"]);
    expect(pressed(chart4(), "Zoom")).toEqual(["All"]);
    expect(svg3()!.getAttribute("data-rows")).toBe("252");
    // Without the $500 grid.
    cleanup();
    show({ ...s1, grids: s1.grids.filter((grid) => grid.step !== 500) });
    await screen.findByText(TITLE4);
    expect(
      within(chart4()).getByText("Chart 4 needs the $500 snapshots, which are missing."),
    ).toBeTruthy();
    expect(svg4()).toBeNull();
    expect(chart4().querySelector(".wh-cf-legend")).toBeNull();
    // A $500 grid without a row is an empty snapshot: no chart, legend or table (A:3569).
    cleanup();
    const empty = structuredClone(s2);
    const grid = empty.grids[0];
    const none = { all: [], sth: [], lth: [] };
    grid.floors = [];
    grid.now = none;
    for (const found of grid.windows) found.then = none;
    empty.age = { groups: [[], [], [], []], band: [] };
    expect(ageRows(empty, "30d", 0)).toEqual({ ok: true, value: [] });
    show(empty);
    await screen.findByText(TITLE4);
    expect(
      within(chart4()).getByText("Chart 4 needs the $500 snapshots, which are missing."),
    ).toBeTruthy();
    expect(svg4()).toBeNull();
    for (const part of [".wh-cf-legend", ".wh-cf-readout", "[data-table]"])
      expect(chart4().querySelector(part)).toBeNull();
  });

  it("draws Chart 4 with the original's 30d readings", async () => {
    show();
    await screen.findByText(TITLE4);
    const page = PAGE4["30d z0"];
    // page-recorded (06:04, expected.chart4_page["30d z0"]): 16 legend rows, the meta, every K row.
    expect(legend4()).toHaveLength(16);
    expect(legend4()).toEqual(page.legend);
    expect(legend4().at(-1)).toBe("net (issuance) / +13,597");
    expect(meta4()).toBe("5 clusters · 1 in · 4 out");
    expect(tableRows("clusters", chart4()).map(line)).toEqual(page.clusters);
    expect(svg4()!.getAttribute("data-rows")).toBe("252");
    expect(svg4()!.querySelectorAll(".wh-cf-bar--sold")).toHaveLength(252);
    // Each bought bar in its group's colour and each sold bar in its band's; a bar of 0 not drawn.
    const rows = rows4("30d", 0);
    for (let g = 0; g < 3; g += 1)
      expect(barsOf(`a${g}`), `a${g}`).toHaveLength(rows.filter((r) => r.buy[g] !== 0).length);
    expect(barsOf("a3")).toHaveLength(0);
    for (let band = 0; band < 12; band += 1)
      expect(barsOf(`s${band}`), `s${band}`).toHaveLength(
        rows.filter((r) => r.band === band && r.sold !== 0).length,
      );
    // The legend's toggle rows are switches in their colours, sold ones marked faint; the net row
    // is not a switch and takes the net colour.
    const keys = [...chart4().querySelectorAll(".wh-cf-legend .wh-seller-key")];
    expect(keys.slice(0, 15).every((key) => key.tagName === "BUTTON")).toBe(true);
    expect(keys.slice(0, 15).every((key) => key.getAttribute("aria-pressed") === "true")).toBe(true);
    expect(keys[15].tagName).toBe("SPAN");
    expect(keys[0].querySelector("i")!.className).toBe(
      "wh-seller-swatch wh-cf-swatch--bought wh-cf-age-0",
    );
    expect(legendRow("sold · last traded 1m–3m ago").querySelector("i")!.className).toBe(
      "wh-seller-swatch wh-cf-swatch--sold wh-cf-age-3",
    );
    expect(keys[15].querySelector("i")!.className).toBe("wh-seller-swatch wh-cf-swatch--net");
    // The axis captions and the note under the legend.
    expect(chart4().querySelector(".wh-cf-captions")!.textContent).toBe(
      "BTC ← Net distributionNet accumulation → BTC",
    );
    expect(chart4().querySelector(".wh-cf-note")!.textContent).toBe(
      "Bought is exact. Sold is grouped by when price was last at that level, which bounds how young those coins can be; drawn faint because it is an inference, not a measurement. Click a legend row to hide it, hover to isolate.",
    );
    // Bells are drawn on the chart only: there is no components table.
    expect(chart4().querySelector('[data-table="components"]')).toBeNull();
    expect(chart4().querySelector(".wh-cf-span")!.textContent).toBe(
      "30d · 19 Sep close → 19 Oct 06:04 UTC",
    );
    // Window and Zoom, Chart 4's three zooms (H:973); both sides at the page's defaults.
    expect(buttons(chart4(), "Window")).toEqual(["1d", "7d", "30d", "90d"]);
    expect(buttons(chart4(), "Zoom")).toEqual(["All", "±50%", "±25%"]);
    expect(pressed(chart4(), "Zoom")).toEqual(["All"]);
    for (const which of ["pos", "neg"] as const) {
      const box = chart4().querySelector<HTMLElement>(`[data-side="${which}"]`)!;
      expect(pressed(box, "Smoothing")).toEqual(["Auto"]);
      expect(pressed(box, "Bell curves")).toEqual(["Off"]);
    }
    // A:3581-3584: unlike Chart 3, the price axis is not padded; the rows run edge to edge.
    const f = plotFrame(720);
    const plotH = 440 - f.top - f.bottom;
    const bars = [...svg4()!.querySelectorAll(".wh-cf-bar")].map((bar) => {
      const y = Number(bar.getAttribute("y"));
      return { top: y, bottom: y + Number(bar.getAttribute("height")) };
    });
    expect(Math.min(...bars.map((bar) => bar.top))).toBeCloseTo(f.top, 0);
    expect(Math.max(...bars.map((bar) => bar.bottom))).toBeCloseTo(f.top + plotH, 0);
    // The K marks are numbered as the table numbers them.
    expect(
      [...svg4()!.querySelectorAll("text.wh-cf-label--k-pos, text.wh-cf-label--k-neg")]
        .map((label) => label.textContent)
        .sort(),
    ).toEqual(["K1", "K2", "K3", "K4", "K5"]);
    expect([...svg4()!.querySelectorAll("text.wh-cf-label--k-pos")].map((l) => l.textContent)).toEqual(
      ["K4"],
    );
    // Each side has its own setting: the sell side unsmoothed keeps only the buy peak.
    const side4 = (which: Side) => chart4().querySelector<HTMLElement>(`[data-side="${which}"]`)!;
    pick(side4("neg"), "Smoothing", "Off");
    expect(meta4()).toBe("1 cluster · 1 in · 0 out");
    expect(tableRows("clusters", chart4()).map((row) => row[1])).toEqual([
      "Net Buy (Accumulation)",
    ]);
    // A:3770: with both sides unsmoothed there is no peak, and Chart 4 says so in its own words.
    pick(side4("pos"), "Smoothing", "Off");
    expect(tableRows("clusters", chart4())).toEqual([["No clusters at this smoothing setting."]]);
    expect(meta4()).toBe("");
    // Chart 3 keeps its own sides.
    expect(tableRows("clusters")).toHaveLength(5);
  });

  it("shares the window with Chart 3 and draws every 90d group", async () => {
    show();
    await screen.findByText(TITLE4);
    pick(chart4(), "Window", "90d");
    expect(pressed(chart3(), "Window")).toEqual(["90d"]);
    expect(pressed(chart4(), "Window")).toEqual(["90d"]);
    // page-recorded (SR-4.md, every group drawn).
    expect(legendRow("bought 1m–3m ago").querySelector("b")!.textContent).toBe("+1,402,425");
    expect(legend4().at(-1)).toBe("net (issuance) / +40,725");
    expect(meta4()).toBe("7 clusters · 2 in · 5 out");
    expect(barsOf("a3").length).toBeGreaterThan(0);
    // Chart 3's buttons move Chart 4 too: 7d, then ±50% (page-recorded).
    pick(chart3(), "Window", "7d");
    expect(pressed(chart4(), "Window")).toEqual(["7d"]);
    expect(legend4()).toEqual(PAGE4["7d z0"].legend);
    pick(chart4(), "Zoom", "±50%");
    expect(pressed(chart3(), "Zoom")).toEqual(["±50%"]);
    expect(legend4()).toEqual(shownNet(PAGE4["7d z50"].legend));
    expect(meta4()).toBe(PAGE4["7d z50"].meta);
  });

  it("hides a group and recomputes only Chart 4", async () => {
    show();
    await screen.findByText(TITLE4);
    pick(chart4(), "Window", "90d");
    const chart3Meta = table("clusters").querySelector(".wh-cf-fit-meta")!.textContent;
    const before = fits.mock.calls.length;
    fireEvent.click(legendRow("bought 1m–3m ago"));
    // page-recorded (the page's 90d state, its fourth group hidden): legend values, meta, clusters.
    expect(legendRow("bought 1m–3m ago").querySelector("b")!.textContent).toBe("off");
    expect(legendRow("bought 1m–3m ago").getAttribute("aria-pressed")).toBe("false");
    expect(legend4().at(-1)).toBe("net of what is shown / −1,361,700");
    expect(legend4()).toEqual(shownNet(PAGE4["90d z0"].legend));
    expect(meta4()).toBe("3 clusters · 1 in · 2 out");
    expect(tableRows("clusters", chart4()).map(line)).toEqual(PAGE4["90d z0"].clusters);
    expect(barsOf("a3")).toHaveLength(0);
    // Exactly Chart 4's two sides were fitted again, on the shown groups; Chart 3 was not.
    const rows = rows4("90d", 0);
    const hidden = { bought: [true, true, true, false], sold: ALL_ON.sold };
    expect(fits.mock.calls.length).toBe(before + 2);
    expect(fits.mock.calls.slice(before).map(([centers, weights]) => [centers, weights])).toEqual([
      [rows.map((r) => r.price), ageWeights(rows, hidden, "pos")],
      [rows.map((r) => r.price), ageWeights(rows, hidden, "neg")],
    ]);
    expect(table("clusters").querySelector(".wh-cf-fit-meta")!.textContent).toBe(chart3Meta);
    // Showing it again restores every group.
    fireEvent.click(legendRow("bought 1m–3m ago"));
    expect(legendRow("bought 1m–3m ago").querySelector("b")!.textContent).toBe("+1,402,425");
    expect(legend4().at(-1)).toBe("net (issuance) / +40,725");
    expect(meta4()).toBe("7 clusters · 2 in · 5 out");
  });

  it("never hides the last visible row", async () => {
    show();
    await screen.findByText(TITLE4);
    // page-recorded: 1d ±25% has six toggle rows.
    pick(chart4(), "Window", "1d");
    pick(chart4(), "Zoom", "±25%");
    expect(legend4()).toEqual(shownNet(PAGE4["1d z25"].legend));
    const labels = [
      "bought <1d ago",
      "sold · last traded <1d ago",
      "sold · last traded 1d–1w ago",
      "sold · last traded 1w–1m ago",
      "sold · last traded 1m–3m ago",
    ];
    for (const label of labels) {
      fireEvent.click(legendRow(label));
      expect(legendRow(label).getAttribute("aria-pressed"), label).toBe("false");
      expect(legendRow(label).querySelector("b")!.textContent, label).toBe("off");
    }
    // Only the 6m–1y sold bars are left; hiding them too is refused and fits nothing.
    const last = "sold · last traded 6m–1y ago";
    expect(svg4()!.querySelectorAll(".wh-cf-bar")).toHaveLength(barsOf("s5").length);
    const before = fits.mock.calls.length;
    fireEvent.click(legendRow(last));
    expect(legendRow(last).getAttribute("aria-pressed")).toBe("true");
    expect(legendRow(last).querySelector("b")!.textContent).toBe("−488");
    expect(barsOf("s5").length).toBeGreaterThan(0);
    expect(fits.mock.calls.length).toBe(before);
  });

  it("resets the toggles, hover and readouts when the window changes", async () => {
    show();
    await screen.findByText(TITLE4);
    // N1: a row hidden, a row isolated and both charts read, in 7d; then 30d from Chart 3.
    pick(chart4(), "Window", "7d");
    const spoil = () => {
      fireEvent.click(legendRow("bought <1d ago"));
      expect(legendRow("bought <1d ago").querySelector("b")!.textContent).toBe("off");
      fireEvent.mouseEnter(legendRow("sold · last traded 1m–3m ago"));
      expect(svg4()!.querySelector(".wh-cf-dim")).not.toBeNull();
      fireEvent.keyDown(svg3()!, { key: "ArrowUp" });
      fireEvent.keyDown(svg4()!, { key: "ArrowUp" });
      expect(readout()).toHaveLength(5);
      expect(readout(chart4()).length).toBeGreaterThan(0);
    };
    const reset = () => {
      expect(
        [...chart4().querySelectorAll(".wh-cf-legend button")].every(
          (key) => key.getAttribute("aria-pressed") === "true",
        ),
      ).toBe(true);
      expect(legend4()).toEqual(PAGE4["30d z0"].legend);
      expect(svg4()!.querySelector(".wh-cf-dim")).toBeNull();
      expect(readout()).toEqual([]);
      expect(readout(chart4())).toEqual([]);
    };
    spoil();
    pick(chart3(), "Window", "30d");
    expect(pressed(chart4(), "Window")).toEqual(["30d"]);
    reset();
    // A window button resets even when it is the window already shown, in either chart.
    spoil();
    pick(chart3(), "Window", "30d");
    reset();
    spoil();
    pick(chart4(), "Window", "30d");
    reset();
  });

  it("keeps the toggles across a zoom unless nothing would be shown", async () => {
    show();
    await screen.findByText(TITLE4);
    // A zoom keeps a hidden row hidden (A:3824-3826).
    fireEvent.click(legendRow("bought <1d ago"));
    pick(chart4(), "Zoom", "±50%");
    expect(legendRow("bought <1d ago").querySelector("b")!.textContent).toBe("off");
    pick(chart4(), "Zoom", "All");
    fireEvent.click(legendRow("bought <1d ago"));
    expect(legend4()).toEqual(PAGE4["30d z0"].legend);
    // Review Focus 3: every row hidden but "10y+", which ±25% does not have: every row comes back.
    for (const row of legend4().slice(0, -1)) {
      const label = row.split(" / ")[0];
      if (label !== "sold · last traded 10y+ ago") fireEvent.click(legendRow(label));
    }
    expect(
      [...chart4().querySelectorAll(".wh-cf-legend button")].filter(
        (key) => key.getAttribute("aria-pressed") === "true",
      ),
    ).toHaveLength(1);
    pick(chart4(), "Zoom", "±25%");
    // page-recorded legend of 30d ±25%, all on; the net is "+253,707".
    expect(legend4()).toEqual(shownNet(PAGE4["30d z25"].legend));
    expect(legend4().at(-1)).toBe("net of what is shown / +253,707");
  });

  // I1: the next snapshot puts every 1w–1m level's last trade under a day, so band 2 leaves the
  // 30d legend; with it the only row left shown.
  const moved = () => {
    const next = structuredClone(s2);
    next.snapshot_at = "2026-10-19T07:04:42Z";
    next.age!.band = next.age!.band.map((band) => (band === 2 ? 0 : band));
    return next;
  };
  const pressedRows = () =>
    [...chart4().querySelectorAll(".wh-cf-legend button")].filter(
      (key) => key.getAttribute("aria-pressed") === "true",
    );

  it("turns every row on when a refresh leaves nothing shown", async () => {
    const { client } = show();
    await screen.findByText(TITLE4);
    const keep = "sold · last traded 1w–1m ago";
    for (const row of legend4().slice(0, -1)) {
      const label = row.split(" / ")[0];
      if (label !== keep) fireEvent.click(legendRow(label));
    }
    expect(pressedRows().map((key) => key.querySelector("span")!.textContent)).toEqual([keep]);
    // Hovered when the refresh comes: its button goes, with no mouseleave. Every drawn bar is
    // its own, so nothing is dimmed yet.
    fireEvent.mouseEnter(legendRow(keep));
    const next = moved();
    await poll(client, next);
    const found = ageRows(next, "30d", 0);
    if (!found.ok) throw new Error(found.missing);
    expect(found.value.some((r) => r.band === 2)).toBe(false);
    // Every row on: the new snapshot's all-on legend, named issuance, and bars drawn.
    expect(
      [...chart4().querySelectorAll(".wh-cf-legend button")].every(
        (key) => key.getAttribute("aria-pressed") === "true",
      ),
    ).toBe(true);
    expect(legend4()).toEqual(
      ageLegend(en, found.value, 3, ALL_ON, 0).map((row) => `${row.label} / ${row.value}`),
    );
    expect(legend4().at(-1)).toMatch(/^net \(issuance\) \/ /);
    expect(svg4()!.querySelectorAll(".wh-cf-bar").length).toBeGreaterThan(0);
    expect(svg4()!.querySelector(".wh-cf-dim")).toBeNull();
    expect(meta4()).not.toBe("");
  });

  it("keeps the toggles across a refresh that leaves a row shown", async () => {
    const { client } = show();
    await screen.findByText(TITLE4);
    fireEvent.click(legendRow("bought <1d ago"));
    // The hovered row is the one the refresh removes.
    fireEvent.mouseEnter(legendRow("sold · last traded 1w–1m ago"));
    expect(svg4()!.querySelector(".wh-cf-dim")).not.toBeNull();
    await poll(client, moved());
    expect(legendRow("bought <1d ago").getAttribute("aria-pressed")).toBe("false");
    expect(legendRow("bought <1d ago").querySelector("b")!.textContent).toBe("off");
    expect(pressedRows()).toHaveLength(legend4().length - 2);
    expect(legend4().at(-1)).toMatch(/^net of what is shown \/ /);
    expect(barsOf("a0")).toHaveLength(0);
    expect(svg4()!.querySelector(".wh-cf-dim")).toBeNull();
  });

  it("follows Chart 3's ±10% zoom with no pill pressed", async () => {
    show();
    await screen.findByText(TITLE4);
    pick(chart3(), "Zoom", "±10%");
    expect(svg4()!.getAttribute("data-rows")).toBe("33");
    expect(pressed(chart4(), "Zoom")).toEqual([]);
    for (const name of ["All", "±50%", "±25%"])
      expect(
        within(within(chart4()).getByRole("group", { name: "Zoom" }))
          .getByRole("button", { name })
          .getAttribute("aria-pressed"),
      ).toBe("false");
    expect(legend4().at(-1)).toMatch(/^net of what is shown \/ /);
    // Chart 4's All takes both charts back.
    pick(chart4(), "Zoom", "All");
    expect(pressed(chart3(), "Zoom")).toEqual(["All"]);
    expect(svg4()!.getAttribute("data-rows")).toBe("252");
  });

  it("isolates a legend row on hover and focus without the engine", async () => {
    show();
    await screen.findByText(TITLE4);
    const before = fits.mock.calls.length;
    const isolated = (key: string) => {
      const own = new Set(barsOf(key));
      const bars = [...svg4()!.querySelectorAll(".wh-cf-bar")];
      expect(own.size, key).toBeGreaterThan(0);
      for (const bar of bars) expect(bar.classList.contains("wh-cf-dim")).toBe(!own.has(bar));
    };
    const row = legendRow("sold · last traded 1m–3m ago");
    fireEvent.mouseEnter(row);
    isolated("s3");
    fireEvent.mouseLeave(row);
    expect(svg4()!.querySelector(".wh-cf-dim")).toBeNull();
    fireEvent.focus(legendRow("bought <1d ago"));
    isolated("a0");
    fireEvent.blur(legendRow("bought <1d ago"));
    expect(svg4()!.querySelector(".wh-cf-dim")).toBeNull();
    // Chart 3 is never dimmed, and nothing was fitted.
    fireEvent.mouseEnter(row);
    expect(svg3()!.querySelector(".wh-cf-dim")).toBeNull();
    expect(fits.mock.calls.length).toBe(before);
    // A click hides the row and ends the isolation; a hidden row isolates nothing.
    fireEvent.click(row);
    expect(svg4()!.querySelector(".wh-cf-dim")).toBeNull();
    fireEvent.mouseEnter(row);
    expect(svg4()!.querySelector(".wh-cf-dim")).toBeNull();
  });

  it("reads a bucket with the keyboard", async () => {
    show();
    await screen.findByText(TITLE4);
    const svg = svg4()!;
    expect(chart4().querySelector(".wh-cf-readout")!.getAttribute("aria-live")).toBe("polite");
    const before = fits.mock.calls.length;
    fireEvent.focus(svg);
    fireEvent.keyDown(svg, { key: "ArrowUp" });
    // page-recorded tooltip format; the first key reads the bucket that holds spot.
    expect(readout(chart4())).toEqual([
      "$82,000 – $82,500",
      "bought <1d ago +73,948",
      "bought 1d–1w ago +95,458",
      "bought 1w–1m ago +67,094",
      "sold from levels last traded <1d ago −16,490",
      "net +220,010",
      "aging removed · 30d window",
    ]);
    expect(svg.querySelector(".wh-cf-cursor")).not.toBeNull();
    // Chart 3 keeps its own reading.
    expect(readout()).toEqual([]);
    fireEvent.keyDown(svg, { key: "End" });
    expect(readout(chart4())[0]).toBe("$125,500 – $126,000");
    fireEvent.keyDown(svg, { key: "Escape" });
    expect(readout(chart4())).toEqual([]);
    expect(fits.mock.calls.length).toBe(before);
  });

  it("puts the three explanations under Chart 4", async () => {
    show();
    await screen.findByText(TITLE4);
    const read = chart4().querySelector(".wh-seller-read")!;
    expect(chart4().lastElementChild).toBe(read);
    expect([...read.querySelectorAll("h4")].map((heading) => heading.textContent)).toEqual([
      "What it shows",
      "What extreme values imply",
      "How to read",
    ]);
    const bodies = [...read.querySelectorAll("p")].map((body) => body.textContent ?? "");
    expect(
      bodies[0].startsWith("The same buying and selling with ageing removed and split by age."),
    ).toBe(true);
    expect(
      bodies[1].startsWith(
        "Summed over every bucket, bought minus sold is the coins mined in the window,",
      ),
    ).toBe(true);
    expect(bodies[2].startsWith("Window and Zoom are shared with Chart 3.")).toBe(true);
    // Chart 4 sits under Chart 3.
    expect(
      chart3().compareDocumentPosition(chart4()) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi, type Mock } from "vitest";
import { CostBasisHistoryChart } from "./cost-basis-history-chart";
import {
  contrast,
  dayLabel,
  dayTicks,
  fmtK,
  paint,
  sortedCells,
  visibleWindow,
} from "./cost-basis-history";
import raw from "./cost-basis-history-sample.json";
import { costBasisHistorySchema, type CostBasisHistoryView } from "./onchain-contract";
import { ticks } from "./sell-side";

// The golden sample (see cost-basis-history.test.ts): 30 days to D = 2026-10-16, forming; 10-15,
// 10-14, 10-09 and 10-08 closed; 10-10 absent at BRK; the rest pending.
const mocks = vi.hoisted(() => ({ history: vi.fn() }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getCostBasisHistory: mocks.history,
}));

const TITLE = "Chart 8 — Cost Basis Distribution, All Coins";
const sample = costBasisHistorySchema.parse(raw);
// useChartWidth's first width, and heightFor(720).
const WIDTH = 720;
const HEIGHT = 338;
// The plot's frame at that width: left 56, right 12, top 10, bottom 24.
const LEFT = 56;
const PLOT_W = WIDTH - LEFT - 12;
const COL = PLOT_W / 30;

let putImageData: Mock;
beforeEach(() => {
  putImageData = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    createImageData: (w: number, h: number) => ({
      width: w,
      height: h,
      data: new Uint8ClampedArray(w * h * 4),
    }),
    putImageData,
  } as never);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

type Answer = CostBasisHistoryView | Error | "pending";
// Each answer serves one request, in order.
function show(...answers: Answer[]) {
  for (const answer of answers) {
    if (answer === "pending") mocks.history.mockReturnValueOnce(new Promise(() => {}));
    else if (answer instanceof Error) mocks.history.mockRejectedValueOnce(answer);
    else mocks.history.mockResolvedValueOnce(answer);
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CostBasisHistoryChart />
    </QueryClientProvider>,
  );
  return client;
}

const panel = () =>
  document.querySelector<HTMLElement>('section[data-chart="cost-basis-history"]')!;
const canvas = () => panel().querySelector("canvas");
const svg = () => panel().querySelector<SVGSVGElement>("svg.wh-cbh-svg")!;
const tip = () => panel().querySelector(".wh-cbh-tip");
const meta = () => panel().querySelector(".wh-seller-meta")!.textContent ?? "";
const zoomNote = () => panel().querySelector(".wh-cbh-zoom")!.textContent;
const group = (name: string) => within(panel()).getByRole("group", { name });
const buttons = (name: string) => within(group(name)).getAllByRole("button");
const pressed = (name: string) =>
  buttons(name)
    .filter((button) => button.getAttribute("aria-pressed") === "true")
    .map((button) => button.textContent);
const pick = (name: string, option: string) =>
  fireEvent.click(within(group(name)).getByRole("button", { name: option }));
const lower = () => within(panel()).getByRole("slider", { name: /^Lower quantile/ });
const upper = () => within(panel()).getByRole("slider", { name: /^Upper quantile/ });
const loaded = () => waitFor(() => expect(canvas()).not.toBeNull());
const sized = () => {
  svg().getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: WIDTH, height: HEIGHT, right: WIDTH, bottom: HEIGHT }) as DOMRect;
};
// A mouse drag between two points of the svg, in its own pixels.
function drag(from: [number, number], to: [number, number]) {
  fireEvent.pointerDown(svg(), {
    clientX: from[0],
    clientY: from[1],
    button: 0,
    pointerType: "mouse",
  });
  fireEvent.pointerMove(svg(), { clientX: to[0], clientY: to[1], pointerType: "mouse" });
  fireEvent.pointerUp(svg(), { clientX: to[0], clientY: to[1], pointerType: "mouse" });
}

it("draws Chart 8 with the original's default controls", async () => {
  show(sample);
  expect(await screen.findByText(TITLE)).toBeTruthy();
  await loaded();
  expect(mocks.history.mock.calls[0][0]).toBe("365");
  expect(buttons("Span").map((button) => button.textContent)).toEqual([
    "30D",
    "90D",
    "365D",
    "All",
  ]);
  expect(pressed("Span")).toEqual(["365D"]);
  expect(within(group("Span")).getByRole("button", { name: "All" }).title).toBe(
    "The last 1,461 days (four years), not the whole history",
  );
  expect(buttons("Range").map((button) => button.textContent)).toEqual([
    "All",
    "±50%",
    "±25%",
    "±10%",
  ]);
  expect(pressed("Range")).toEqual(["All"]);
  expect((lower() as HTMLInputElement).value).toBe("75");
  expect((upper() as HTMLInputElement).value).toBe("95");
  expect(within(panel()).getByText("75–95% · 87k–197k+")).toBeTruthy();
  expect(
    [...panel().querySelectorAll(".wh-cbh-key .wh-cbh-mark")].map((mark) => mark.textContent),
  ).toEqual(["−87k", "115k", "142k", "170k", "197k+"]);
  // Below the floor is shown while the floor drops cells.
  expect(panel().querySelector(".wh-cbh-key")!.textContent).toContain("below floor");
  expect(canvas()!.getAttribute("data-cols")).toBe("30");
  expect(canvas()!.getAttribute("data-rows")).toBe("250");
  const image = putImageData.mock.calls.at(-1)![0] as ImageData;
  expect([image.width, image.height]).toEqual([30, 250]);
  // The pixels are paint's, with the default Contrast over every row.
  const { vis } = visibleWindow(sample, null);
  const out = new Uint8ClampedArray(30 * 250 * 4);
  paint(vis, 0, 249, contrast(sortedCells(vis, 0, 249), 75, 95), out);
  expect(image.data).toEqual(out);
  // The canvas sits on the plot, in shares of the svg's frame, so it stays on the plot at any
  // drawn size: one pixel per day across, one per row down.
  const share = (value: string) => {
    expect(value).toMatch(/%$/);
    return parseFloat(value);
  };
  expect(share(canvas()!.style.left)).toBeCloseTo((LEFT / WIDTH) * 100, 6);
  expect(share(canvas()!.style.top)).toBeCloseTo((10 / HEIGHT) * 100, 6);
  expect(share(canvas()!.style.width)).toBeCloseTo((PLOT_W / WIDTH) * 100, 6);
  expect(share(canvas()!.style.height)).toBeCloseTo(((HEIGHT - 34) / HEIGHT) * 100, 6);
  expect(svg().getAttribute("viewBox")).toBe(`0 0 ${WIDTH} ${HEIGHT}`);
  expect(svg().getAttribute("role")).toBe("img");
  expect(svg().getAttribute("tabindex")).toBe("0");
  expect(svg().getAttribute("aria-label")).toMatch(/^Chart 8 heatmap: supply by cost basis/);
  // Axes: d3's linear ticks on the price and its time ticks on the days.
  const labels = [...svg().querySelectorAll("text")].map((label) => label.textContent);
  // The price axis runs from floors[0] to the top of floors[249] = $125,500 (A:4088).
  for (const label of ticks(1000, 126000, 7).map(fmtK)) expect(labels).toContain(label);
  for (const label of dayTicks("2026-09-17", "2026-10-16", 5).map((d) => dayLabel(d, 29)))
    expect(labels).toContain(label);
  // Each time label sits on its day's column centre (plan R13a).
  for (const day of dayTicks("2026-09-17", "2026-10-16", 5)) {
    const tick = [...svg().querySelectorAll('text[text-anchor="middle"]')].find(
      (label) => label.textContent === dayLabel(day, 29),
    )!;
    expect(Number(tick.getAttribute("x"))).toBeCloseTo(LEFT + (sample.days.indexOf(day) + 0.5) * COL, 1);
  }
  expect(labels).toContain("UTC");
  expect(zoomNote()).toBe("drag the chart to zoom");
  expect(panel().querySelector(".wh-cbh-tip")).toBeNull();
  // The span on screen is asked for again only after it failed.
  pick("Span", "365D");
  expect(mocks.history).toHaveBeenCalledTimes(1);
});

it("hatches missing days and outlines the forming one", async () => {
  show(sample);
  await loaded();
  const missing = [...panel().querySelectorAll("[data-missing]")];
  expect(missing.map((rect) => rect.getAttribute("data-days"))).toEqual(["21", "4"]);
  // Column bands (plan R13a): the 21 pending days from the left edge, and 10-10 to 10-13.
  expect(Number(missing[0].getAttribute("x"))).toBeCloseTo(LEFT, 1);
  expect(Number(missing[0].getAttribute("width"))).toBeCloseTo(21 * COL, 1);
  expect(Number(missing[1].getAttribute("x"))).toBeCloseTo(LEFT + 23 * COL, 1);
  expect(Number(missing[1].getAttribute("width"))).toBeCloseTo(4 * COL, 1);
  expect(missing[0].getAttribute("fill")).toMatch(/^url\(#.+-hatch\)$/);
  const pattern = panel().querySelector("pattern")!;
  expect(missing[0].getAttribute("fill")).toBe(`url(#${pattern.id})`);
  expect(pattern.querySelector("line.wh-perp-hatch")).not.toBeNull();
  const forming = panel().querySelectorAll('[data-forming="true"]');
  expect(forming).toHaveLength(1);
  expect(Number(forming[0].getAttribute("x"))).toBeCloseTo(LEFT + 29 * COL, 1);
  expect(Number(forming[0].getAttribute("width"))).toBeCloseTo(COL, 1);
  // The spot line breaks at the missing days: 10-08 to 10-09, then 10-14 to 10-16.
  const price = panel().querySelector("path.wh-cbh-price")!.getAttribute("d")!;
  expect(price.match(/M/g)).toHaveLength(2);
  expect(price.match(/L/g)).toHaveLength(3);
  expect(panel().querySelector("path.wh-cbh-price-case")!.getAttribute("d")).toBe(price);
  expect(Number(price.slice(1).split(",")[0])).toBeCloseTo(LEFT + 21.5 * COL, 1);
  const status = meta();
  expect(status).toContain("Snapshot 2026-10-16 UTC");
  expect(status).toContain("5 of 30 days stored");
  expect(status).toContain("the rest is still being fetched");
  expect(status).toContain("1 day has no snapshot at BRK");
  expect(status).toContain("The last column is today's snapshot, still forming");
});

it("Range ±25 narrows the rows", async () => {
  show(sample);
  await loaded();
  pick("Range", "±25%");
  expect(pressed("Range")).toEqual(["±25%"]);
  expect(canvas()!.getAttribute("data-rows")).toBe("84");
  expect(within(panel()).getByText("75–95% · 143k–239k+")).toBeTruthy();
  const image = putImageData.mock.calls.at(-1)![0] as ImageData;
  expect([image.width, image.height]).toEqual([30, 84]);
  // The price axis is rows 119 to 202, $60,500 to $102,500, with d3's 7-tick steps.
  expect(
    [...svg().querySelectorAll('text[text-anchor="end"]')].map((label) => label.textContent),
  ).toEqual(ticks(60500, 102500, 7).map(fmtK));
});

it("Span All asks for 1,461 days and keeps the chart while it loads", async () => {
  show(sample, "pending");
  await loaded();
  pick("Span", "All");
  await waitFor(() => expect(mocks.history).toHaveBeenCalledTimes(2));
  expect(mocks.history.mock.calls[1][0]).toBe("all");
  expect(within(panel()).getByText("loading 1,461 days…")).toBeTruthy();
  expect(canvas()).not.toBeNull();
  expect(canvas()!.getAttribute("data-cols")).toBe("30");
  expect(pressed("Span")).toEqual(["All"]);
});

it("clamps the contrast handles", async () => {
  show(sample);
  await loaded();
  fireEvent.change(upper(), { target: { value: "10" } });
  expect((upper() as HTMLInputElement).value).toBe("76");
  fireEvent.change(lower(), { target: { value: "99" } });
  expect((lower() as HTMLInputElement).value).toBe("75");
  expect((upper() as HTMLInputElement).value).toBe("76");
  // The handles share one track and the upper one is drawn over the lower: from the middle up, the
  // lower one is raised, so at 99 and 100 it can still be grabbed.
  const raised = () => lower().classList.contains("wh-cbh-raised");
  expect(raised()).toBe(true);
  fireEvent.change(upper(), { target: { value: "100" } });
  fireEvent.change(lower(), { target: { value: "99" } });
  expect((lower() as HTMLInputElement).value).toBe("99");
  expect(raised()).toBe(true);
  fireEvent.change(lower(), { target: { value: "50" } });
  expect(raised()).toBe(true);
  fireEvent.change(lower(), { target: { value: "49" } });
  expect(raised()).toBe(false);
  expect(upper().classList.contains("wh-cbh-raised")).toBe(false);
  // Both handles at the ends: the whole range, nothing below the floor, nothing clipped.
  fireEvent.change(lower(), { target: { value: "0" } });
  fireEvent.change(upper(), { target: { value: "100" } });
  expect(within(panel()).getByText("full range")).toBeTruthy();
  const key = panel().querySelector(".wh-cbh-key")!;
  expect(key.textContent).not.toContain("below floor");
  const marks = [...key.querySelectorAll(".wh-cbh-mark")].map((mark) => mark.textContent);
  expect(marks).toHaveLength(5);
  expect(marks.join(" ")).not.toMatch(/[−+]/);
});

it("reads a day with the keyboard and says when it is missing", async () => {
  show(sample);
  await loaded();
  // The live region is mounted before the first reading, so that reading is announced too.
  const live = panel().querySelector(".wh-cbh-live")!;
  expect(live.getAttribute("aria-live")).toBe("polite");
  expect(live.textContent).toBe("");
  act(() => svg().focus());
  expect(fireEvent.keyDown(svg(), { key: "ArrowLeft" })).toBe(false);
  expect(panel().querySelector(".wh-cbh-live")).toBe(live);
  expect(live.contains(tip())).toBe(true);
  let text = tip()!.textContent;
  expect(text).toContain("2026-10-15");
  expect(text).toContain("Bucket $81.0k–$81.5k");
  expect(text).toContain(
    `Supply ${Math.round(sample.supply[28]![160]).toLocaleString("en-US")} BTC`,
  );
  expect(text).toContain("spot $82k");
  expect(text).not.toContain("forming");
  // The cursor crosses the cell: column 28's centre, and the middle of the $81,000 row.
  const [across, down] = [...svg().querySelectorAll("line.wh-seller-cursor")];
  expect(Number(across.getAttribute("x1"))).toBeCloseTo(LEFT + 28.5 * COL, 1);
  expect(Number(down.getAttribute("y1"))).toBeCloseTo(10 + (304 * (126000 - 81250)) / 125000, 1);
  expect(fireEvent.keyDown(svg(), { key: "ArrowUp" })).toBe(false);
  expect(tip()!.textContent).toContain("Bucket $81.5k–$82.0k");
  expect(fireEvent.keyDown(svg(), { key: "ArrowDown" })).toBe(false);
  expect(tip()!.textContent).toContain("Bucket $81.0k–$81.5k");
  expect(fireEvent.keyDown(svg(), { key: "ArrowLeft" })).toBe(false);
  expect(fireEvent.keyDown(svg(), { key: "ArrowLeft" })).toBe(false);
  text = tip()!.textContent;
  expect(text).toContain("2026-10-13");
  expect(text).toContain("No snapshot stored for this day yet");
  expect(text).not.toContain("Bucket");
  expect(text).not.toMatch(/BTC/);
  expect(fireEvent.keyDown(svg(), { key: "ArrowLeft" })).toBe(false);
  expect(fireEvent.keyDown(svg(), { key: "ArrowLeft" })).toBe(false);
  expect(fireEvent.keyDown(svg(), { key: "ArrowLeft" })).toBe(false);
  expect(tip()!.textContent).toContain("2026-10-10");
  expect(tip()!.textContent).toContain("BRK has no snapshot for this day");
  expect(fireEvent.keyDown(svg(), { key: "End" })).toBe(false);
  text = tip()!.textContent;
  expect(text).toContain("2026-10-16");
  expect(text).toContain("forming");
  expect(text).toContain("spot $81k");
  expect(fireEvent.keyDown(svg(), { key: "ArrowRight" })).toBe(false);
  expect(tip()!.textContent).toContain("2026-10-16");
  expect(fireEvent.keyDown(svg(), { key: "Home" })).toBe(false);
  expect(tip()!.textContent).toContain("2026-09-17");
  expect(fireEvent.keyDown(svg(), { key: "Escape" })).toBe(false);
  expect(tip()).toBeNull();
  expect(panel().querySelector(".wh-cbh-live")).toBe(live);
  expect(live.textContent).toBe("");
  // Other keys pass through to the page.
  expect(fireEvent.keyDown(svg(), { key: "Tab" })).toBe(true);
});

it("starts reading on the last day in view, at the row of the latest close in view", async () => {
  show(sample);
  await loaded();
  sized();
  // 10-08 to 10-12: the last two days are pending, 10-09 closed at $82,361 (row 162).
  drag([LEFT + 21.5 * COL, 100], [LEFT + 25.5 * COL, 102]);
  expect(canvas()!.getAttribute("data-cols")).toBe("5");
  act(() => svg().focus());
  fireEvent.keyDown(svg(), { key: "ArrowLeft" });
  expect(tip()!.textContent).toContain("2026-10-11");
  fireEvent.keyDown(svg(), { key: "Home" });
  expect(tip()!.textContent).toContain("2026-10-08");
  expect(tip()!.textContent).toContain("Bucket $82.0k–$82.5k");
});

it("reads the cell under the pointer and leaves with the mouse", async () => {
  show(sample);
  await loaded();
  sized();
  // Column 28 (10-15), and the row whose $500 bucket holds $81,250: the plot is 304 px tall from
  // y = 10 and the price axis runs from $1,000 to $126,000.
  const y = 10 + (304 * (126000 - 81250)) / 125000;
  fireEvent.pointerMove(svg(), {
    clientX: LEFT + 28.5 * COL,
    clientY: y,
    pointerType: "mouse",
  });
  expect(tip()!.textContent).toContain("2026-10-15");
  expect(tip()!.textContent).toContain("Bucket $81.0k–$81.5k");
  // Outside the plot there is nothing to read.
  fireEvent.pointerMove(svg(), { clientX: 10, clientY: y, pointerType: "mouse" });
  expect(tip()).toBeNull();
  fireEvent.pointerMove(svg(), { clientX: LEFT + 0.5 * COL, clientY: y, pointerType: "mouse" });
  expect(tip()!.textContent).toContain("2026-09-17");
  fireEvent.pointerLeave(svg(), { pointerType: "mouse" });
  expect(tip()).toBeNull();
});

it("drags a box to zoom and resets it", async () => {
  show(sample);
  await loaded();
  sized();
  fireEvent.pointerDown(svg(), { clientX: 100, clientY: 40, button: 0, pointerType: "mouse" });
  fireEvent.pointerMove(svg(), { clientX: 400, clientY: 200, pointerType: "mouse" });
  expect(svg().querySelector("rect.wh-cbh-drag")).not.toBeNull();
  fireEvent.pointerUp(svg(), { clientX: 400, clientY: 200, pointerType: "mouse" });
  expect(zoomNote()).toMatch(
    /^\d\d-\d\d–\d\d-\d\d · \$[\d.]+k–\$[\d.]+k · double-click to reset$/,
  );
  fireEvent.click(within(panel()).getByRole("button", { name: "Reset zoom" }));
  expect(zoomNote()).toBe("drag the chart to zoom");
  expect(within(panel()).queryByRole("button", { name: "Reset zoom" })).toBeNull();
  await loaded();
  expect(canvas()!.getAttribute("data-cols")).toBe("30");
});

it("keeps the dragged days when a later drag only sets the price band", async () => {
  show(sample);
  await loaded();
  sized();
  // Across 10-08 to 10-16 only: no price band.
  drag([LEFT + 21.5 * COL, 100], [LEFT + 29.5 * COL, 102]);
  expect(zoomNote()).toBe("10-08–10-16 · double-click to reset");
  expect(canvas()!.getAttribute("data-cols")).toBe("9");
  // Down only: the price band joins the days.
  sized();
  drag([300, 40], [302, 200]);
  const band = /^10-08–10-16 · (\$[\d.]+k–\$[\d.]+k) · double-click to reset$/.exec(zoomNote()!);
  expect(band).not.toBeNull();
  // Across again: new days, the same band.
  sized();
  const col = PLOT_W / 9;
  drag([LEFT + 0.5 * col, 100], [LEFT + 4.5 * col, 102]);
  expect(zoomNote()).toBe(`10-08–10-12 · ${band![1]} · double-click to reset`);
  // A double-click undoes both.
  fireEvent.doubleClick(svg());
  expect(zoomNote()).toBe("drag the chart to zoom");
  expect(canvas()!.getAttribute("data-cols")).toBe("30");
});

it("offers Reset zoom when the dragged days hold no snapshot", async () => {
  show(sample);
  await loaded();
  sized();
  // Columns 2 to 15, all pending.
  drag([LEFT + 2.5 * COL, 100], [LEFT + 15.5 * COL, 102]);
  expect(canvas()).toBeNull();
  expect(
    within(panel()).getByText("None of the days in view has a stored snapshot: missing, not zero"),
  ).toBeTruthy();
  expect(meta()).toContain("0 of 14 days stored");
  expect(panel().textContent).not.toMatch(/\b0 BTC/);
  expect(panel().querySelector(".wh-cbh-key")).toBeNull();
  fireEvent.click(within(panel()).getByRole("button", { name: "Reset zoom" }));
  await loaded();
  expect(canvas()!.getAttribute("data-cols")).toBe("30");
});

it("reads a tap without zooming", async () => {
  show(sample);
  await loaded();
  sized();
  fireEvent.pointerDown(svg(), {
    clientX: LEFT + 28.5 * COL,
    clientY: 100,
    pointerType: "touch",
  });
  expect(tip()!.textContent).toContain("2026-10-15");
  fireEvent.pointerMove(svg(), { clientX: 100, clientY: 250, pointerType: "touch" });
  expect(svg().querySelector("rect.wh-cbh-drag")).toBeNull();
  fireEvent.pointerUp(svg(), { clientX: 100, clientY: 250, pointerType: "touch" });
  expect(zoomNote()).toBe("drag the chart to zoom");
});

it("drops the dragged days on a new span and the price band on a new range", async () => {
  show(sample, "pending");
  await loaded();
  sized();
  drag([LEFT + 21.5 * COL, 40], [LEFT + 29.5 * COL, 200]);
  expect(zoomNote()).toMatch(/^10-08–10-16 · \$[\d.]+k–\$[\d.]+k · double-click to reset$/);
  pick("Span", "90D");
  expect(zoomNote()).toMatch(/^\$[\d.]+k–\$[\d.]+k · double-click to reset$/);
  pick("Range", "±50%");
  expect(zoomNote()).toBe("drag the chart to zoom");
});

it("shows no data, never zero, when nothing in view is stored", async () => {
  const none: CostBasisHistoryView = {
    ...sample,
    close: sample.close.map(() => null),
    supply: sample.supply.map(() => null),
    status: sample.status.map(() => "pending" as const),
  };
  show(none);
  await screen.findByText("None of the days in view has a stored snapshot: missing, not zero");
  expect(canvas()).toBeNull();
  expect(panel().textContent).not.toMatch(/\b0 BTC/);
  expect(panel().querySelector(".wh-cbh-key")).toBeNull();
  expect(meta()).toContain("0 of 30 days stored");
  cleanup();
  // Stored days without a cell above the data's precision: no data, and still no zero.
  const empty: CostBasisHistoryView = {
    ...sample,
    supply: sample.supply.map((row) => row && row.map(() => 0)),
  };
  show(empty);
  await screen.findByText("No data for this chart");
  expect(canvas()).toBeNull();
  expect(panel().textContent).not.toMatch(/\b0 BTC/);
  expect(panel().querySelector(".wh-cbh-key")).toBeNull();
});

it("unavailable, failed and stale", async () => {
  show({
    ...sample,
    data_state: "unavailable",
    reasons: ["urpd_missing"],
    latest_day: null,
    floors: [],
    days: [],
    close: [],
    supply: [],
    status: [],
  });
  expect(await screen.findByText("Cost basis history unavailable")).toBeTruthy();
  expect(screen.getByText("URPD distribution unavailable")).toBeTruthy();
  expect(canvas()).toBeNull();
  cleanup();
  show(new Error("Python service did not respond. Check the local workspace and retry."));
  expect(await screen.findByText("Cost basis history unavailable")).toBeTruthy();
  expect(
    screen.getByText("Python service did not respond. Check the local workspace and retry."),
  ).toBeTruthy();
  cleanup();
  show({ ...sample, data_state: "stale", reasons: ["brk_unavailable"], refreshing: true });
  expect(
    await screen.findByText("Latest snapshot is 2026-10-16; the data is stale"),
  ).toBeTruthy();
  await loaded();
  expect(within(panel()).getByText("on-chain data source unavailable")).toBeTruthy();
  expect(within(panel()).getByText("Refreshing on-chain data…")).toBeTruthy();
  expect(within(panel()).getByText("Rules: original v1")).toBeTruthy();
});

it("has the three notes and the original caption", async () => {
  show(sample);
  await loaded();
  for (const heading of ["What it shows", "What extreme values imply", "How to read"])
    expect(within(panel()).getByRole("heading", { name: heading })).toBeTruthy();
  expect(panel().textContent).toContain(
    "Where the cost basis of every coin sits, day by day. Each column is one day's snapshot",
  );
  expect(panel().querySelector(".wh-ss-foot")!.textContent).toBe(
    "Supply by $500 cost-basis bucket, one column per day, with spot overlaid. Contrast sets which quantile band of supply the colour ramp is spent on; it rescales the colour, it does not remove supply. Excludes cost basis under $1,000.",
  );
});

it("keeps the last chart when a new span fails to load", async () => {
  show(sample, new Error("Python service did not respond. Check the local workspace and retry."));
  await loaded();
  pick("Span", "All");
  expect(await within(panel()).findByText("could not load 1,461 days")).toBeTruthy();
  expect(canvas()).not.toBeNull();
  expect(canvas()!.getAttribute("data-cols")).toBe("30");
  expect(within(panel()).queryByText("Cost basis history unavailable")).toBeNull();
  expect(pressed("Span")).toEqual(["All"]);
  // Picking All again retries it.
  mocks.history.mockReturnValueOnce(new Promise(() => {}));
  pick("Span", "All");
  await waitFor(() => expect(mocks.history).toHaveBeenCalledTimes(3));
  expect(mocks.history.mock.calls[2][0]).toBe("all");
  expect(await within(panel()).findByText("loading 1,461 days…")).toBeTruthy();
  expect(canvas()!.getAttribute("data-cols")).toBe("30");
});

it("shows unavailable when the span on screen fails to refresh", async () => {
  const client = show(
    sample,
    new Error("Python service did not respond. Check the local workspace and retry."),
  );
  await loaded();
  await act(() => client.refetchQueries());
  expect(await within(panel()).findByText("Cost basis history unavailable")).toBeTruthy();
  expect(canvas()).toBeNull();
  // Span stays, so the failed span can be asked for again, or another one picked.
  expect(pressed("Span")).toEqual(["365D"]);
  let answer: (view: CostBasisHistoryView) => void = () => {};
  mocks.history.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
  pick("Span", "365D");
  expect(mocks.history).toHaveBeenCalledTimes(3);
  // The retry says it is under way.
  expect(await within(panel()).findByText("loading 365 days…")).toBeTruthy();
  expect(within(panel()).getByText("Cost basis history unavailable")).toBeTruthy();
  await act(async () => answer(sample));
  await loaded();
  expect(within(panel()).queryByText("Cost basis history unavailable")).toBeNull();
  expect(within(panel()).queryByText("loading 365 days…")).toBeNull();
});

it("never draws an older span's days after the span on screen failed", async () => {
  const failure = new Error("Python service did not respond. Check the local workspace and retry.");
  const client = show(sample, failure);
  await loaded();
  await act(() => client.refetchQueries());
  expect(await within(panel()).findByText("Cost basis history unavailable")).toBeTruthy();
  let refuse: (error: Error) => void = () => {};
  mocks.history.mockReturnValueOnce(new Promise((_resolve, reject) => (refuse = reject)));
  pick("Span", "90D");
  await waitFor(() => expect(mocks.history).toHaveBeenCalledTimes(3));
  expect(mocks.history.mock.calls[2][0]).toBe("90");
  // While 90D loads, the 365 days that failed to refresh are not shown in its place.
  expect(await within(panel()).findByText("Loading the cost basis history…")).toBeTruthy();
  expect(canvas()).toBeNull();
  await act(async () => refuse(failure));
  expect(await within(panel()).findByText("Cost basis history unavailable")).toBeTruthy();
  expect(canvas()).toBeNull();
  expect(within(panel()).queryByText("could not load 90 days")).toBeNull();
  expect(pressed("Span")).toEqual(["90D"]);
});

it("says loading while a span that failed to refresh is asked for again", async () => {
  const failure = new Error("Python service did not respond. Check the local workspace and retry.");
  const client = show(sample);
  await loaded();
  // 365D's refresh, which fails, then 90D.
  let fail: (error: Error) => void = () => {};
  mocks.history.mockReturnValueOnce(new Promise((_resolve, reject) => (fail = reject)));
  mocks.history.mockResolvedValueOnce(sample);
  act(() => void client.refetchQueries());
  await waitFor(() => expect(mocks.history).toHaveBeenCalledTimes(2));
  // A refresh of the span on screen is no new span loading.
  expect(within(panel()).queryByText("loading 365 days…")).toBeNull();
  await act(async () => fail(failure));
  expect(await within(panel()).findByText("Cost basis history unavailable")).toBeTruthy();
  pick("Span", "90D");
  await loaded();
  // Back on 365D: its cached days failed, so they are asked for again as it mounts. With days
  // cached the query stays in error while it fetches.
  let refuse: (error: Error) => void = () => {};
  mocks.history.mockReturnValueOnce(new Promise((_resolve, reject) => (refuse = reject)));
  pick("Span", "365D");
  await waitFor(() => expect(mocks.history).toHaveBeenCalledTimes(4));
  expect(mocks.history.mock.calls[3][0]).toBe("365");
  expect(await within(panel()).findByText("loading 365 days…")).toBeTruthy();
  expect(within(panel()).queryByText("could not load 365 days")).toBeNull();
  expect(canvas()).not.toBeNull();
  await act(async () => refuse(failure));
  expect(await within(panel()).findByText("could not load 365 days")).toBeTruthy();
  expect(within(panel()).queryByText("loading 365 days…")).toBeNull();
  expect(canvas()).not.toBeNull();
});

it("polls hourly for All and every 15 minutes otherwise", async () => {
  const client = show(sample, "pending");
  await loaded();
  const every = (span: string) =>
    client.getQueryCache().find({ queryKey: ["wh", "onchain", "cost-basis-history", span] })!
      .observers[0].options.refetchInterval;
  expect(every("365")).toBe(900_000);
  pick("Span", "All");
  await waitFor(() => expect(mocks.history).toHaveBeenCalledTimes(2));
  expect(every("all")).toBe(3_600_000);
});

it("says when the backfill is paused", async () => {
  show({ ...sample, backfill_error: "brk_unavailable" });
  await loaded();
  expect(meta()).toContain(
    "history fetch paused: BRK returned brk_unavailable; retrying next hour",
  );
  expect(meta()).not.toContain("the rest is still being fetched");
});

it("says when a failed refresh holds the backfill", async () => {
  // A failed round leaves the gate shut whatever the last backfill did; sync_failed is no BRK code.
  show({ ...sample, last_error: "sync_failed", backfill_error: "brk_unavailable" });
  await loaded();
  expect(meta()).toContain(
    "history fetch paused: the last refresh failed (sync_failed); it resumes after the next successful refresh",
  );
  expect(meta()).not.toContain("the rest is still being fetched");
  expect(meta()).not.toContain("BRK returned");
  expect(meta()).not.toContain("next hour");
  cleanup();
  // Nothing pending: there is no backfill to hold.
  const stored: CostBasisHistoryView = {
    ...sample,
    last_error: "brk_unavailable",
    days: sample.days.slice(-2),
    close: sample.close.slice(-2),
    supply: sample.supply.slice(-2),
    status: sample.status.slice(-2),
  };
  show(stored);
  await loaded();
  expect(meta()).toContain("2 of 2 days stored");
  expect(meta()).not.toContain("paused");
});

it("says the backfill waits when there is no newest snapshot", async () => {
  // BRK had no D: the round succeeded with no error, yet the gate is shut, whatever the last
  // backfill did.
  show({
    ...sample,
    data_state: "stale",
    reasons: ["urpd_missing"],
    backfill_error: "brk_unavailable",
  });
  await loaded();
  expect(meta()).toContain(
    "history fetch waits for the newest snapshot; it resumes once BRK has it",
  );
  expect(meta()).not.toContain("the rest is still being fetched");
  expect(meta()).not.toContain("BRK returned");
  cleanup();
  // A failed round is still said first.
  show({ ...sample, reasons: ["urpd_missing"], last_error: "brk_unavailable" });
  await loaded();
  expect(meta()).toContain("the last refresh failed (brk_unavailable)");
  expect(meta()).not.toContain("waits for the newest snapshot");
  cleanup();
  // Nothing pending: there is no backfill to wait for.
  show({
    ...sample,
    reasons: ["urpd_missing"],
    days: sample.days.slice(-2),
    close: sample.close.slice(-2),
    supply: sample.supply.slice(-2),
    status: sample.status.slice(-2),
  });
  await loaded();
  expect(meta()).not.toContain("waits");
  expect(meta()).not.toContain("paused");
});

it("names each day BRK has no snapshot of", async () => {
  show({
    ...sample,
    status: sample.status.map((status, i) => (i === 11 || i === 12 ? "absent" : status)),
  });
  await loaded();
  expect(meta()).toContain("3 days have no snapshot at BRK");
});

it("clears the readout when inputs or data change", async () => {
  const client = show(sample, { ...sample, computed_at: "2026-10-16T19:29:37Z" }, "pending");
  await loaded();
  sized();
  act(() => svg().focus());
  fireEvent.keyDown(svg(), { key: "ArrowLeft" });
  expect(tip()).not.toBeNull();
  pick("Range", "±25%");
  expect(tip()).toBeNull();
  fireEvent.keyDown(svg(), { key: "ArrowLeft" });
  expect(tip()).not.toBeNull();
  fireEvent.change(upper(), { target: { value: "90" } });
  expect(tip()).toBeNull();
  // A drag reads cells on its way; the zoom it ends in clears them.
  drag([300, 40], [302, 200]);
  expect(zoomNote()).not.toBe("drag the chart to zoom");
  expect(tip()).toBeNull();
  fireEvent.keyDown(svg(), { key: "ArrowLeft" });
  expect(tip()).not.toBeNull();
  await act(() => client.refetchQueries());
  await waitFor(() => expect(mocks.history).toHaveBeenCalledTimes(2));
  expect(tip()).toBeNull();
  fireEvent.keyDown(svg(), { key: "ArrowLeft" });
  expect(tip()).not.toBeNull();
  pick("Span", "90D");
  expect(tip()).toBeNull();
});

const shifted = (view: CostBasisHistoryView, days: number): CostBasisHistoryView => ({
  ...view,
  days: view.days.map((day) => new Date(Date.parse(day) + days * 864e5).toISOString().slice(0, 10)),
});

it("drops a dragged window the new days no longer cover", async () => {
  const client = show(sample, shifted(sample, 2));
  await loaded();
  sized();
  // The two oldest days, both pending.
  drag([LEFT + 0.2 * COL, 100], [LEFT + 1.5 * COL, 102]);
  expect(zoomNote()).toBe("09-17–09-18 · double-click to reset");
  expect(canvas()).toBeNull();
  await act(() => client.refetchQueries());
  await loaded();
  expect(zoomNote()).toBe("drag the chart to zoom");
  expect(within(panel()).queryByRole("button", { name: "Reset zoom" })).toBeNull();
  expect(canvas()!.getAttribute("data-cols")).toBe("30");
});

it("holds the spot line to the plot and drops a band that keeps no row", async () => {
  const client = show(sample, {
    ...sample,
    computed_at: "2026-10-16T19:29:37Z",
    supply: sample.supply.map((row) => row && row.map((v, i) => (i > 150 ? 0 : v))),
  });
  await loaded();
  sized();
  // The top of the chart, about $114k to $125k: spot, near $82k, is under it.
  drag([300, 12], [302, 40]);
  expect(zoomNote()).toMatch(/^\$11\dk–\$12\dk · double-click to reset$/);
  const d = panel().querySelector("path.wh-cbh-price")!.getAttribute("d")!;
  const ys = [...d.matchAll(/[ML][\d.]+,([\d.]+)/g)].map((m) => Number(m[1]));
  expect(ys).toHaveLength(5);
  // Held to the bottom edge of the plot: 10 + 304.
  for (const y of ys) expect(y).toBe(314);
  // The new days hold nothing above row 150, so the band keeps no row and is dropped.
  await act(() => client.refetchQueries());
  await waitFor(() => expect(zoomNote()).toBe("drag the chart to zoom"));
  expect(canvas()).not.toBeNull();
});


it("says no data when the dragged band holds no coins", async () => {
  // Rows 100 to 150, $51,000 to $76,500, hold nothing on any stored day.
  show({
    ...sample,
    supply: sample.supply.map((row) => row && row.map((v, i) => (i >= 100 && i <= 150 ? 0 : v))),
  });
  await loaded();
  sized();
  // $74,000 down to $56,000.
  drag([300, 10 + (304 * 52000) / 125000], [302, 10 + (304 * 70000) / 125000]);
  expect(zoomNote()).toBe("$56k–$74k · double-click to reset");
  expect(canvas()).toBeNull();
  expect(within(panel()).getByText("No data for this chart")).toBeTruthy();
  expect(panel().querySelector(".wh-cbh-key")).toBeNull();
  expect(panel().querySelector(".wh-cbh-level")).toBeNull();
  fireEvent.click(within(panel()).getByRole("button", { name: "Reset zoom" }));
  await loaded();
});

import {
  act,
  cleanup,
  fireEvent,
  render,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { messages } from "./i18n";
import { PerpCharts } from "./perp-charts";
import { perpStatesSample, type PerpStatesView } from "./perps-contract";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

type ChartKey = "c1" | "c2" | "c3" | "c4";

const titles: Record<ChartKey, string> = {
  c1: "Chart 1 — Price: long/short squeezes and unwinds",
  c2: "Chart 2 — Price: new long, new short, spot-led",
  c3: "Chart 3 — Price vs open interest",
  c4: "Chart 4 — Volume delta and liquidations",
};

function draw(
  view: PerpStatesView = perpStatesSample(),
  { show = 30, verified = true }: { show?: number; verified?: boolean } = {},
) {
  return render(<PerpCharts view={view} show={show} verified={verified} />);
}

const chart = (key: ChartKey) =>
  document.querySelector<HTMLElement>(`[data-chart="${key}"]`);
const panel = (key: ChartKey) => {
  const found = chart(key);
  if (!found) throw new Error(`no ${key}`);
  return found;
};
const bands = (key: ChartKey) =>
  [...panel(key).querySelectorAll("rect.wh-perp-band")].map(
    (band) => band.getAttribute("data-state") ?? "",
  );
const marks = (key: ChartKey, kind: string) =>
  [...panel(key).querySelectorAll(`[data-uncovered="${kind}"]`)].map((mark) =>
    mark.getAttribute("data-t0"),
  );
const bars = (kind: "buy" | "sell" | "short" | "long") =>
  [...panel("c4").querySelectorAll(`rect.wh-perp-bar--${kind}`)].map((bar) =>
    bar.getAttribute("data-t0"),
  );
// The number of points on a path, and the number of separate pieces it is drawn in.
const pathOf = (key: ChartKey, name: "price" | "oi") =>
  panel(key).querySelector(`path.wh-perp-${name}`)?.getAttribute("d") ?? "";
const points = (d: string) => (d.match(/[ML]/g) ?? []).length;
const pieces = (d: string) => (d.match(/M/g) ?? []).length;
const legend = (key: ChartKey) =>
  [...panel(key).querySelectorAll(".wh-perp-legend > *")].map(
    (item) => item.textContent ?? "",
  );
const reading = (key: ChartKey) =>
  panel(key).querySelector(".wh-perp-reading")?.textContent ?? "";
// The reading's labelled values, one per item.
const values = (key: ChartKey) =>
  [
    ...panel(key).querySelectorAll(
      ".wh-perp-reading > span:not(.wh-perp-when):not(.wh-perp-notes)",
    ),
  ].map((item) => item.textContent ?? "");
const svg = (key: ChartKey) => panel(key).querySelector("svg")!;

const SQUEEZE_UNWIND = ["longsq", "shortsq", "longun", "shortun"];
const BUILD_SPOT = ["longbd", "shortbd", "spot"];

it("draws the four charts, shading squeezes and unwinds in Chart 1 and builds and spot-led in Chart 2", () => {
  draw();
  for (const [key, title] of Object.entries(titles))
    expect(
      within(panel(key as ChartKey)).getByRole("heading", { name: title }),
    ).toBeTruthy();
  expect(bands("c1")).toHaveLength(38);
  expect(bands("c1").every((state) => SQUEEZE_UNWIND.includes(state))).toBe(
    true,
  );
  expect(bands("c2")).toHaveLength(48);
  expect(bands("c2").every((state) => BUILD_SPOT.includes(state))).toBe(true);
  // Chop is judged and counted but never shaded.
  expect(document.querySelector('.wh-perp-band[data-state="chop"]')).toBeNull();
  // One point per block at the block's close: 181 blocks overlap the 30-day view.
  for (const key of ["c1", "c2", "c3"] as const) {
    expect(points(pathOf(key, "price"))).toBe(181);
    expect(pieces(pathOf(key, "price"))).toBe(1);
  }
  expect(points(pathOf("c3", "oi"))).toBe(181);
  expect(bars("buy").length + bars("sell").length).toBe(181);
  expect(bars("short")).toHaveLength(181);
  expect(bars("long")).toHaveLength(181);
  expect(document.querySelector("[data-uncovered]")).toBeNull();
});

it("draws only the 7d view's blocks, shading the one across its left edge", () => {
  const view = perpStatesSample();
  // The block from 08:00 straddles the 7d view's start at 10:50.
  const edge = view.blocks.findIndex(
    (block) => block.t0 === "2026-10-10T08:00:00Z",
  );
  view.blocks[edge] = { ...view.blocks[edge], state: "longsq" };
  draw(view, { show: 7 });
  expect(points(pathOf("c1", "price"))).toBe(43);
  expect(bands("c1")).toHaveLength(9);
  expect(bands("c2")).toHaveLength(12);
  const band = panel("c1").querySelector<SVGRectElement>(
    'rect.wh-perp-band[data-t0="2026-10-10T08:00:00Z"]',
  )!;
  const plot = panel("c1").querySelector("clipPath rect")!;
  // Clipped to the view: it starts at the plot's left edge and covers only the part in view.
  expect(band.getAttribute("x")).toBe(plot.getAttribute("x"));
  const width = (rect: Element) => Number(rect.getAttribute("width"));
  const full = [...panel("c1").querySelectorAll("rect.wh-perp-band")].find(
    (rect) => rect !== band,
  )!;
  // 10:50 to 12:00 of a block from 08:00 to 12:00.
  expect(width(band) / width(full)).toBeCloseTo(70 / 240, 2);
});

it("hatches uncovered blocks apart from the shading and leaves Chart 4 empty there", () => {
  draw(perpStatesSample("uncovered"));
  const uncovered = ["2026-09-17T08:00:00Z", "2026-10-17T08:00:00Z"];
  for (const key of ["c1", "c2"] as const) {
    expect(marks(key, "block")).toEqual(uncovered);
    for (const mark of panel(key).querySelectorAll("[data-uncovered]"))
      expect(mark.getAttribute("fill")).toMatch(/^url\(#.+-hatch\)$/);
  }
  expect(bands("c1")).toHaveLength(38);
  expect(bands("c2")).toHaveLength(48);
  expect(marks("c4", "delta")).toEqual(uncovered);
  expect(marks("c4", "liq")).toEqual(uncovered);
  for (const t0 of uncovered) {
    expect([...bars("buy"), ...bars("sell")]).not.toContain(t0);
    expect([...bars("short"), ...bars("long")]).not.toContain(t0);
  }
  expect(bars("short")).toHaveLength(179);
});

it("leaves a partly covered block's bars empty even when it has partial sums", () => {
  const view = perpStatesSample();
  const k = 100;
  const t0 = view.blocks[k].t0;
  view.blocks[k] = {
    ...view.blocks[k],
    liq_covered: false,
    covered: false,
    state: null,
  };
  view.blocks[k + 1] = {
    ...view.blocks[k + 1],
    delta_covered: false,
    covered: false,
    state: null,
  };
  draw(view);
  expect(marks("c4", "liq")).toEqual([t0]);
  expect(marks("c4", "delta")).toEqual([view.blocks[k + 1].t0]);
  expect([...bars("short"), ...bars("long")]).not.toContain(t0);
  expect([...bars("buy"), ...bars("sell")]).toContain(t0);
  expect([...bars("buy"), ...bars("sell")]).not.toContain(
    view.blocks[k + 1].t0,
  );
  expect(bars("short")).toContain(view.blocks[k + 1].t0);
});

it("draws no delta bar and no marker for a covered block whose delta is all missing", () => {
  const view = perpStatesSample();
  view.blocks[50] = { ...view.blocks[50], delta_sum: null };
  draw(view);
  expect(bars("buy").length + bars("sell").length).toBe(180);
  expect(panel("c4").querySelector("[data-uncovered]")).toBeNull();
});

it("counts judged blocks centred in view in the legend, and the uncovered ones apart", () => {
  draw();
  expect(legend("c1")).toEqual([
    "Long squeeze 9 / 180",
    "Short squeeze 7 / 180",
    "Long unwind 10 / 180",
    "Short unwind 12 / 180",
    "BTC/USD",
  ]);
  expect(legend("c2")).toEqual([
    "New long build 9 / 180",
    "New short build 9 / 180",
    "Spot-led 30 / 180",
    "BTC/USD",
  ]);
  cleanup();
  draw(perpStatesSample("uncovered"));
  // The oldest block is centred before the view; the forming one is in it, uncovered.
  expect(legend("c1")).toEqual([
    "Long squeeze 9 / 179",
    "Short squeeze 7 / 179",
    "Long unwind 10 / 179",
    "Short unwind 12 / 179",
    "(+1 uncovered)",
    "BTC/USD",
  ]);
});

it("counts the legend by the nominal block midpoint, not Table 1's", () => {
  const view = perpStatesSample();
  // The forming block (08:00, 18 buckets) is centred at 09:30 by its buckets, which Table 1
  // uses, but at 10:00 by its nominal length, which the legend uses.
  view.tables[0] = { ...view.tables[0], view_from: "2026-10-17T09:40:00Z" };
  draw(view, { show: 7 });
  expect(legend("c1").slice(0, 4)).toEqual([
    "Long squeeze 0 / 1",
    "Short squeeze 0 / 1",
    "Long unwind 0 / 1",
    "Short unwind 0 / 1",
  ]);
});

it("shows — in the legend when no block in view is judged", () => {
  const view = perpStatesSample("uncovered");
  view.tables[0] = { ...view.tables[0], view_from: "2026-10-17T09:40:00Z" };
  draw(view, { show: 7 });
  expect(legend("c2")).toEqual([
    "New long build —",
    "New short build —",
    "Spot-led —",
    "(+1 uncovered)",
    "BTC/USD",
  ]);
});

it("hides and shows a state's shading from its legend item", () => {
  draw();
  const toggle = within(panel("c1")).getByRole("button", {
    name: /^Long squeeze/,
  });
  expect(toggle.getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-pressed")).toBe("false");
  expect(bands("c1")).toHaveLength(29);
  expect(bands("c1")).not.toContain("longsq");
  // The count stays: hiding is about the drawing, not the data.
  expect(toggle.textContent).toBe("Long squeeze 9 / 180");
  expect(bands("c2")).toHaveLength(48);
  fireEvent.click(toggle);
  expect(bands("c1")).toHaveLength(38);
});

it("tags the squeezes in the legend until the direction is verified", () => {
  draw(perpStatesSample(), { verified: false });
  expect(legend("c1").slice(0, 3)).toEqual([
    "Long squeeze (direction unverified) 9 / 180",
    "Short squeeze (direction unverified) 7 / 180",
    "Long unwind 10 / 180",
  ]);
});

it("reads a block from the keyboard with its imputed flags, uncovered and a zero threshold", () => {
  const view = perpStatesSample();
  const n = view.blocks.length;
  view.blocks[n - 1] = {
    ...view.blocks[n - 1],
    imputed: { dpx: true, doi: true, sums: false },
  };
  // An uncovered block always has imputed sums: its liquidations count as 0 in the rules.
  view.blocks[n - 2] = {
    ...view.blocks[n - 2],
    liq_covered: false,
    covered: false,
    state: null,
    imputed: { dpx: false, doi: false, sums: true },
  };
  view.thresholds = { ...view.thresholds!, s_liq: 0 };
  draw(view);
  const latest = reading("c1");
  expect(latest).toContain("Latest · 2026-10-17 08:00 → 12:00 UTC");
  expect(latest).toContain("BTC/USD $56,968.8");
  expect(latest).toContain("Block Chop");
  expect(latest).toContain("forming");
  expect(latest).toContain("imputed: price change, OI change");
  expect(latest).toContain("liquidation threshold is 0");

  fireEvent.keyDown(svg("c1"), { key: "ArrowLeft" });
  expect(reading("c1")).toContain("2026-10-17 04:00 → 08:00 UTC");
  expect(reading("c1")).not.toContain("Latest");
  expect(reading("c1")).toContain("Block uncovered");
  // Not judged, so neither imputed inputs nor the threshold decided anything.
  expect(reading("c1")).not.toContain("imputed");
  expect(reading("c1")).not.toContain("threshold");
  fireEvent.keyDown(svg("c4"), { key: "ArrowLeft" });
  expect(reading("c4")).toContain("Short liquidations uncovered");
  expect(reading("c4")).toContain("Long liquidations uncovered");
  expect(reading("c4")).toContain("Volume delta 204 BTC");

  fireEvent.keyDown(svg("c1"), { key: "ArrowLeft" });
  expect(reading("c1")).toContain("2026-10-17 00:00 → 04:00 UTC");
  expect(reading("c1")).toContain("liquidation threshold is 0");
  fireEvent.keyDown(svg("c1"), { key: "Home" });
  expect(reading("c1")).toContain("2026-09-17 08:00 → 12:00 UTC");
  fireEvent.keyDown(svg("c1"), { key: "Escape" });
  expect(reading("c1")).toContain("Latest · 2026-10-17 08:00 → 12:00 UTC");
  // Each chart keeps its own reading.
  expect(reading("c3")).toContain("Latest");
  expect(reading("c3")).toContain("Open interest 159k BTC");
});

it("makes every chart a focusable image named for the keyboard", () => {
  draw();
  for (const key of ["c1", "c2", "c3", "c4"] as const) {
    expect(svg(key).getAttribute("tabindex")).toBe("0");
    expect(svg(key).getAttribute("role")).toBe("img");
    expect(svg(key).getAttribute("aria-label")).toBe(
      `${titles[key]}. Use the left and right arrow keys to read one block; Escape returns to the latest.`,
    );
    expect(
      panel(key).querySelector(".wh-perp-reading")?.getAttribute("aria-live"),
    ).toBe("polite");
  }
});

it("draws the tail short of half a block without judging it", () => {
  const view = perpStatesSample();
  const n = view.blocks.length;
  view.blocks[n - 1] = {
    ...view.blocks[n - 1],
    t1: "2026-10-17T11:50:00Z",
    buckets: 24,
    forming: false,
  };
  view.last = "2026-10-17T12:30:00Z";
  const tail = {
    t0: "2026-10-17T12:00:00Z",
    t1: "2026-10-17T12:30:00Z",
    price_close: 57010,
    oi_close: 158900,
    delta_sum: -12,
    lliq_sum: 1,
    sliq_sum: 2,
  };
  view.tail = tail;
  draw(view);
  expect(points(pathOf("c1", "price"))).toBe(182);
  expect(points(pathOf("c3", "oi"))).toBe(182);
  // Its coverage is unknown, so Chart 4 leaves it out: no bar, no hatching, no reading.
  const atTail = '[data-t0="2026-10-17T12:00:00Z"]';
  expect(panel("c1").querySelector(atTail)).toBeNull();
  expect(panel("c4").querySelector(atTail)).toBeNull();
  expect(bars("sell")).not.toContain("2026-10-17T12:00:00Z");
  // The tail ends at its last bucket, not at a whole block.
  expect(reading("c1")).toContain("Latest · 2026-10-17 12:00 → 12:40 UTC");
  expect(reading("c1")).toContain("Block partial block, not judged");
  expect(reading("c1")).toContain("BTC/USD $57,010.0");
  expect(reading("c3")).toContain("Open interest 159k BTC");
  for (const name of [
    "Volume delta",
    "Short liquidations",
    "Long liquidations",
  ])
    expect(reading("c4")).toContain(`${name} —`);
  // Its sums stay out of the scales too: huge ones leave the axes as no sums do.
  const ticks = (side: "left" | "right") =>
    [...panel("c4").querySelectorAll(`.wh-perp-tick--${side}`)].map(
      (tick) => tick.textContent,
    );
  cleanup();
  view.tail = { ...tail, delta_sum: -5000, sliq_sum: 900 };
  draw(view);
  const withHugeTail = [ticks("left"), ticks("right")];
  cleanup();
  view.tail = { ...tail, delta_sum: null, sliq_sum: null, lliq_sum: null };
  draw(view);
  expect([ticks("left"), ticks("right")]).toEqual(withHugeTail);
});

it("draws 8h blocks twice as wide, counting and reading them by 8h", () => {
  const view = perpStatesSample();
  view.window = "8h";
  // Synthetic 8h blocks: every 4h block that starts on an 8h boundary, stretched to 48 buckets;
  // the last 18 buckets (08:00 to 10:50) are short of half an 8h block, so they are the tail.
  const forming = view.blocks.at(-1)!;
  view.blocks = view.blocks
    .filter(
      (block) =>
        new Date(block.t0).getUTCHours() % 8 === 0 && block !== forming,
    )
    .map((block) => ({
      ...block,
      t1: new Date(Date.parse(block.t0) + 470 * 60_000).toISOString(),
      buckets: 48,
      forming: false,
    }));
  view.tail = {
    t0: forming.t0,
    t1: forming.t1,
    price_close: forming.price_close,
    oi_close: forming.oi_close,
    delta_sum: forming.delta_sum,
    lliq_sum: forming.lliq_sum,
    sliq_sum: forming.sliq_sum,
  };
  draw(view);
  expect(points(pathOf("c1", "price"))).toBe(91);
  expect(bands("c1")).toHaveLength(32);
  expect(legend("c1")[0]).toBe("Long squeeze 8 / 90");
  const plot = panel("c1").querySelector("clipPath rect")!;
  const band = panel("c1").querySelectorAll("rect.wh-perp-band")[1];
  // An 8h block is 1/90 of the 30-day view.
  expect(
    Number(band.getAttribute("width")) / Number(plot.getAttribute("width")),
  ).toBeCloseTo(1 / 90, 3);
  expect(reading("c1")).toContain("Latest · 2026-10-17 08:00 → 11:00 UTC");
  fireEvent.keyDown(svg("c1"), { key: "ArrowLeft" });
  expect(reading("c1")).toContain("2026-10-17 00:00 → 08:00 UTC");
});

it("moves the reading with ArrowRight, End and leaving the chart", () => {
  draw();
  const target = svg("c2");
  for (let k = 0; k < 3; k += 1)
    fireEvent.keyDown(target, { key: "ArrowLeft" });
  expect(reading("c2")).toContain("2026-10-16 20:00 → 00:00 UTC");
  fireEvent.keyDown(target, { key: "ArrowRight" });
  expect(reading("c2")).toContain("2026-10-17 00:00 → 04:00 UTC");
  fireEvent.keyDown(target, { key: "End" });
  expect(reading("c2")).toContain("Latest · 2026-10-17 08:00 → 12:00 UTC");
  // ArrowRight stops at the latest block.
  fireEvent.keyDown(target, { key: "ArrowRight" });
  expect(reading("c2")).toContain("2026-10-17 08:00 → 12:00 UTC");
  fireEvent.keyDown(target, { key: "ArrowLeft" });
  fireEvent.blur(target);
  expect(reading("c2")).toContain("Latest");
});

it("reads the block under the pointer, keeping it when a finger lifts", () => {
  draw();
  const target = svg("c1");
  // The chart draws 720 wide in tests, with its plot from 52 to 668: 360 is half way through
  // the 30-day view, 10-02 10:50, inside the block from 08:00.
  target.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: 720, height: 210 }) as DOMRect;
  fireEvent.pointerMove(target, { clientX: 360, pointerType: "mouse" });
  expect(reading("c1")).toContain("2026-10-02 08:00 → 12:00 UTC");
  expect(panel("c1").querySelector("rect.wh-perp-cursor")).toBeTruthy();
  fireEvent.pointerLeave(target, { pointerType: "touch" });
  expect(reading("c1")).toContain("2026-10-02 08:00 → 12:00 UTC");
  fireEvent.pointerLeave(target, { pointerType: "mouse" });
  expect(reading("c1")).toContain("Latest");
  expect(panel("c1").querySelector("rect.wh-perp-cursor")).toBeNull();
  // Left of the plot reads the first block; right of it the latest.
  fireEvent.pointerDown(target, { clientX: 0, pointerType: "touch" });
  expect(reading("c1")).toContain("2026-09-17 08:00 → 12:00 UTC");
  fireEvent.pointerMove(target, { clientX: 719, pointerType: "mouse" });
  expect(reading("c1")).toContain("2026-10-17 08:00 → 12:00 UTC");
});

it("draws no delta axis when no block has a delta", () => {
  const view = perpStatesSample();
  view.blocks = view.blocks.map((block) => ({ ...block, delta_sum: null }));
  draw(view);
  expect(panel("c4").querySelector(".wh-perp-tick--left")).toBeNull();
  expect(bars("buy").length + bars("sell").length).toBe(0);
  expect(panel("c4").querySelector(".wh-perp-tick--right")).toBeTruthy();
});

it("follows the chart's width once it is drawn, also when it appears late", () => {
  const observed: { el: Element; fire: (width: number) => void }[] = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      callback: ResizeObserverCallback;
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback;
      }
      observe(el: Element) {
        observed.push({
          el,
          fire: (width) =>
            this.callback(
              [{ contentRect: { width } } as ResizeObserverEntry],
              this as unknown as ResizeObserver,
            ),
        });
      }
      disconnect() {}
    },
  );
  const empty = { ...perpStatesSample(), blocks: [], tail: null };
  const { rerender } = draw(empty);
  expect(within(panel("c3")).getByText("No blocks in this view")).toBeTruthy();
  expect(observed).toHaveLength(0);
  rerender(<PerpCharts view={perpStatesSample()} show={30} verified />);
  const c3 = observed.find((item) => item.el === svg("c3"));
  expect(c3).toBeTruthy();
  act(() => c3!.fire(400));
  expect(svg("c3").getAttribute("viewBox")).toBe("0 0 400 180");
});

it("breaks the price line where a block has no price", () => {
  const view = perpStatesSample();
  view.blocks[100] = { ...view.blocks[100], price_close: null };
  draw(view);
  expect(pieces(pathOf("c1", "price"))).toBe(2);
  expect(points(pathOf("c1", "price"))).toBe(180);
});

it("draws only Charts 3 and 4 while collecting", () => {
  draw(perpStatesSample("collecting"));
  expect(chart("c1")).toBeNull();
  expect(chart("c2")).toBeNull();
  expect(points(pathOf("c3", "oi"))).toBe(21);
  expect(bars("short")).toHaveLength(21);
});

it("keeps three expanded notes under every chart, outside any details element", () => {
  draw();
  for (const key of ["c1", "c2", "c3", "c4"] as const) {
    const headings = [...panel(key).querySelectorAll(".wh-perp-read h4")];
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "What it shows",
      "What extreme values imply",
      "How to read",
    ]);
    for (const heading of headings) {
      expect(heading.closest("details")).toBeNull();
      expect((heading.parentElement?.textContent ?? "").length).toBeGreaterThan(
        (heading.textContent ?? "").length + 40,
      );
    }
  }
  expect(document.querySelectorAll("details")).toHaveLength(0);
});

it("has Chinese copy for every chart key, written apart from the English", () => {
  const keys = Object.keys(messages.en).filter(
    (key) => key.startsWith("perp.chart") || /^perp\.c\d\./.test(key),
  );
  expect(keys.length).toBeGreaterThan(30);
  for (const key of keys) {
    const zh = messages.zh[key as keyof typeof messages.zh];
    expect(zh.length).toBeGreaterThan(0);
    if (/\.(shows|implies|how|title)$/.test(key))
      expect(zh).not.toBe(messages.en[key as keyof typeof messages.en]);
  }
});

it("says on hover why a covered block was not judged, and shows its own thresholds", () => {
  draw(perpStatesSample("ruled"));
  // The latest block is forming: O1 draws it only. Charts 1 and 2 say so in its value.
  const latest = reading("c1");
  expect(latest).toContain("Latest · 2026-10-17 08:00 → 12:00 UTC");
  expect(latest).toContain("Block not judged: still forming");
  expect(values("c1")).toEqual([
    "BTC/USD $60,595.7",
    "Block not judged: still forming",
    "Short liq. threshold 38.2 BTC",
    "Long liq. threshold 36.6 BTC",
    "OI change threshold 280 BTC",
    "Price change threshold 0.70%",
  ]);
  // Its value says it is forming, so Charts 1 and 2 need no note; Chart 3 keeps it.
  expect(panel("c1").querySelector(".wh-perp-notes")).toBeNull();
  expect(panel("c3").querySelector(".wh-perp-notes")?.textContent).toBe(
    "forming",
  );

  // The last closed block is judged against its own thresholds, those heading the view.
  fireEvent.keyDown(svg("c1"), { key: "ArrowLeft" });
  expect(reading("c1")).toContain("2026-10-17 04:00 → 08:00 UTC");
  expect(values("c1").slice(1)).toEqual([
    "Block Chop",
    "Short liq. threshold 37.8 BTC",
    "Long liq. threshold 35.8 BTC",
    "OI change threshold 281 BTC",
    "Price change threshold 0.70%",
  ]);

  // The first block has no close before it and nothing before it to rank on.
  fireEvent.keyDown(svg("c1"), { key: "Home" });
  expect(reading("c1")).toContain("2026-10-07 00:00 → 04:00 UTC");
  expect(values("c1").slice(1)).toEqual([
    "Block not judged: imputed inputs, fewer than 42 reference blocks",
    "Short liq. threshold —",
    "Long liq. threshold —",
    "OI change threshold —",
    "Price change threshold —",
  ]);
  // Block 42 ranks 42 liquidations but only 41 price changes.
  fireEvent.keyDown(svg("c2"), { key: "Home" });
  for (let k = 0; k < 42; k += 1)
    fireEvent.keyDown(svg("c2"), { key: "ArrowRight" });
  expect(reading("c2")).toContain("2026-10-14 00:00 → 04:00 UTC");
  expect(values("c2").slice(1)).toEqual([
    "Block not judged: fewer than 42 reference blocks",
    "Short liq. threshold 37.7 BTC",
    "Long liq. threshold 36.8 BTC",
    "OI change threshold 284 BTC",
    "Price change threshold —",
  ]);
  // Block 55 has no OI close.
  for (let k = 42; k < 55; k += 1)
    fireEvent.keyDown(svg("c2"), { key: "ArrowRight" });
  expect(reading("c2")).toContain("2026-10-16 04:00 → 08:00 UTC");
  expect(reading("c2")).toContain("Block not judged: imputed inputs");
  // Charts 3 and 4 read no states and no thresholds.
  fireEvent.keyDown(svg("c4"), { key: "Home" });
  expect(reading("c4")).not.toContain("threshold");
  expect(reading("c4")).not.toContain("not judged");
});

it("names 21 reference blocks for an 8h view", () => {
  const view = perpStatesSample("ruled");
  view.window = "8h";
  draw(view);
  fireEvent.keyDown(svg("c1"), { key: "Home" });
  expect(reading("c1")).toContain("fewer than 21 reference blocks");
});

it("counts the covered blocks left unjudged apart in the legend", () => {
  draw(perpStatesSample("ruled"));
  expect(legend("c1")).toEqual([
    "Long squeeze 1 / 18",
    "Short squeeze 1 / 18",
    "Long unwind 1 / 18",
    "Short unwind 0 / 18",
    "(+45 not judged)",
    "BTC/USD",
  ]);
  // Only judged blocks are tinted.
  expect(bands("c1")).toHaveLength(3);
  expect(bands("c2")).toHaveLength(2);
  expect(document.querySelector("[data-uncovered]")).toBeNull();
});

it("keeps the zero-threshold note and the past-tense caveat to v1", () => {
  const view = perpStatesSample("ruled");
  view.thresholds = { ...view.thresholds!, s_liq: 0 };
  draw(view);
  fireEvent.keyDown(svg("c1"), { key: "ArrowLeft" });
  expect(reading("c1")).toContain("Block Chop");
  expect(reading("c1")).not.toContain("liquidation threshold is 0");
  const how = (key: ChartKey) =>
    panel(key).querySelectorAll(".wh-perp-read p")[2].textContent ?? "";
  expect(how("c1")).toMatch(/use only the 90 days before it/);
  expect(how("c1")).not.toMatch(/came later/);
  cleanup();
  draw();
  expect(how("c1")).toMatch(/include blocks that came later/);
});

it("draws Charts 1 and 2 while collecting once some blocks are judged", () => {
  draw({ ...perpStatesSample("ruled"), collecting: true });
  expect(chart("c1")).toBeTruthy();
  expect(chart("c2")).toBeTruthy();
});

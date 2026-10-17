import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { messages } from "./i18n";
import { PerpCharts } from "./perp-charts";
import { perpStatesSample, type PerpStatesView } from "./perps-contract";

afterEach(cleanup);

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
  view.blocks[n - 2] = {
    ...view.blocks[n - 2],
    liq_covered: false,
    covered: false,
    state: null,
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
  view.tail = {
    t0: "2026-10-17T12:00:00Z",
    t1: "2026-10-17T12:30:00Z",
    price_close: 57010,
    oi_close: 158900,
    delta_sum: -12,
    lliq_sum: 1,
    sliq_sum: 2,
  };
  draw(view);
  expect(points(pathOf("c1", "price"))).toBe(182);
  expect(points(pathOf("c3", "oi"))).toBe(182);
  expect(bars("sell")).toContain("2026-10-17T12:00:00Z");
  expect(
    panel("c1").querySelector('[data-t0="2026-10-17T12:00:00Z"]'),
  ).toBeNull();
  expect(reading("c1")).toContain("Latest · 2026-10-17 12:00 → 16:00 UTC");
  expect(reading("c1")).toContain("Block partial block, not judged");
  expect(reading("c1")).toContain("BTC/USD $57,010.0");
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

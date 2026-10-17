import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { messages } from "./i18n";
import { pressureSample, type SellerPressureView } from "./onchain-contract";
import {
  SellerCharts,
  compactUsd,
  percent,
  sigUsd,
  usdPrice,
} from "./seller-charts";

const mocks = vi.hoisted(() => ({ pressure: vi.fn() }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getSellerPressure: mocks.pressure,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show(
  view: SellerPressureView | Error | "pending",
  cached?: SellerPressureView,
) {
  if (view === "pending") mocks.pressure.mockReturnValue(new Promise(() => {}));
  else if (view instanceof Error) mocks.pressure.mockRejectedValue(view);
  else mocks.pressure.mockResolvedValue(view);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  // An earlier successful reading, which a failed refetch leaves in the cache.
  if (cached) client.setQueryData(["wh", "onchain", "seller-pressure"], cached);
  const rendered = render(
    <QueryClientProvider client={client}>
      <SellerCharts />
    </QueryClientProvider>,
  );
  return { client, ...rendered };
}

const unavailable = (reasons: string[]): SellerPressureView => ({
  data_state: "unavailable",
  reasons,
  refreshing: false,
  forming_at: null,
  last_at: null,
  loss: [],
  share: [],
  supply: [],
  price: [],
  loss_levels: null,
  share_levels: null,
  supply_levels: null,
  xgap: null,
  qc: [],
  brk_version: null,
  rules: [],
  rules_pending: false,
});

const chart = (container: HTMLElement, name: "loss" | "share" | "supply") =>
  container.querySelector<HTMLElement>(`[data-chart="${name}"]`)!;
const points = (container: HTMLElement, name: "loss" | "share" | "supply") =>
  Number(
    chart(container, name).querySelector("svg")!.getAttribute("data-points"),
  );
const pathOf = (el: HTMLElement, selector: string) =>
  el.querySelector(selector)?.getAttribute("d") ?? "";
const moves = (d: string) => (d.match(/M/g) ?? []).length;

// Drops one hour from a series so its neighbours are two hours apart.
const without = <T extends { at: string }>(rows: T[], index: number) =>
  rows.filter((_, i) => i !== index);

it("shows the three chart titles, the header levels and the current values", async () => {
  const { container } = show(pressureSample());
  expect(
    await screen.findByText("Chart 1 — Total realized loss by cohorts (USD)"),
  ).toBeTruthy();
  expect(
    screen.getByText(
      "Chart 2 — STH realized loss as a share of the sell side (%)",
    ),
  ).toBeTruthy();
  expect(screen.getByText("Chart 3 — STH supply in loss (%)")).toBeTruthy();

  const head = (name: "loss" | "share" | "supply") =>
    chart(container, name).querySelector(".wh-seller-head")!;
  const legend = (name: "loss" | "share" | "supply") =>
    chart(container, name).querySelector(".wh-seller-legend")!.textContent ??
    "";
  const levels = (name: "loss" | "share" | "supply") =>
    [".wh-seller-extreme", ".wh-seller-warning"].map(
      (selector) => head(name).querySelector(selector)?.textContent,
    );
  expect(levels("loss")).toEqual(["$41.3M", "$10.1M"]);
  expect(levels("share")).toEqual(["56.1%", "22.2%"]);
  expect(levels("supply")).toEqual(["38.7%", "26.2%"]);
  expect(head("loss").textContent).toContain("$41.3M");
  expect(head("loss").textContent).toContain("$10.1M");

  expect(legend("loss")).toContain("LTH loss $1.98M");
  expect(legend("loss")).toContain("STH loss $8.54M");
  expect(legend("share")).toContain("41.9%");
  expect(legend("supply")).toContain("29.6%");
  // the original rounds the price to one decimal
  for (const name of ["loss", "share", "supply"] as const)
    expect(legend(name)).toMatch(/BTC\/USD \$[\d,]+\.\d(?!\d)/);
});

it("defaults to 30d and slices each chart on its own span", async () => {
  const { container } = show(pressureSample());
  await screen.findByText("Chart 3 — STH supply in loss (%)");
  for (const name of ["loss", "share", "supply"] as const) {
    expect(points(container, name)).toBe(720);
    const pressed = within(chart(container, name))
      .getAllByRole("button")
      .filter((button) => button.getAttribute("aria-pressed") === "true");
    expect(pressed.map((button) => button.textContent)).toEqual(["30d"]);
  }
  expect(
    chart(container, "share").querySelectorAll("rect.wh-seller-bar"),
  ).toHaveLength(720);

  fireEvent.click(
    within(chart(container, "share")).getByRole("button", { name: "7d" }),
  );
  expect(points(container, "share")).toBe(168);
  expect(
    chart(container, "share").querySelectorAll("rect.wh-seller-bar").length,
  ).toBeLessThanOrEqual(168);
  expect(points(container, "loss")).toBe(720);
  expect(points(container, "supply")).toBe(720);

  fireEvent.click(
    within(chart(container, "supply")).getByRole("button", { name: "90d" }),
  );
  expect(points(container, "supply")).toBe(2160);
  expect(points(container, "share")).toBe(168);
  expect(points(container, "loss")).toBe(720);
});

it("draws bars only for positive shares and stacks LTH under STH", async () => {
  const view = pressureSample();
  view.share[view.share.length - 2].value = 0;
  const { container } = show(view);
  await screen.findByText(
    "Chart 2 — STH realized loss as a share of the sell side (%)",
  );
  expect(
    chart(container, "share").querySelectorAll("rect.wh-seller-bar"),
  ).toHaveLength(719);
  expect(
    chart(container, "loss").querySelectorAll("rect.wh-seller-bar--lth"),
  ).toHaveLength(720);
  expect(
    chart(container, "loss").querySelectorAll("rect.wh-seller-bar--sth"),
  ).toHaveLength(720);
});

it("shows nine explanations, all expanded and outside any details element", async () => {
  const { container } = show(pressureSample());
  await screen.findByText("Chart 3 — STH supply in loss (%)");
  expect(container.querySelectorAll("details")).toHaveLength(0);
  for (const name of ["loss", "share", "supply"] as const) {
    const headings = [
      ...chart(container, name).querySelectorAll(".wh-seller-read h4"),
    ];
    expect(headings.map((heading) => heading.textContent)).toEqual([
      "What it shows",
      "What extreme values imply",
      "How to read",
    ]);
    for (const heading of headings) {
      expect(heading.closest("details")).toBeNull();
      expect((heading.parentElement?.textContent ?? "").length).toBeGreaterThan(
        (heading.textContent ?? "").length + 20,
      );
    }
  }
});

it("breaks the price line and chart 3's line where hours are missing", async () => {
  const view = pressureSample();
  view.price = without(view.price, 2000);
  view.supply = without(view.supply, 2100);
  const { container } = show(view);
  await screen.findByText("Chart 3 — STH supply in loss (%)");
  expect(moves(pathOf(chart(container, "loss"), "path.wh-seller-price"))).toBe(
    2,
  );
  expect(moves(pathOf(chart(container, "supply"), "path.wh-seller-line"))).toBe(
    2,
  );
  // the 30d window of every chart contains the missing price hour
  expect(moves(pathOf(chart(container, "share"), "path.wh-seller-price"))).toBe(
    2,
  );
});

it("keeps one piece when no hour is missing", async () => {
  const { container } = show(pressureSample());
  await screen.findByText("Chart 3 — STH supply in loss (%)");
  for (const name of ["loss", "share", "supply"] as const)
    expect(moves(pathOf(chart(container, name), "path.wh-seller-price"))).toBe(
      1,
    );
  expect(moves(pathOf(chart(container, "supply"), "path.wh-seller-line"))).toBe(
    1,
  );
});

it("treats an exact one-hour step as continuous and any other step as a break", async () => {
  const view = pressureSample();
  // shifting one price point by a minute is not exactly one hour from its neighbours
  view.price[2100] = {
    ...view.price[2100],
    at: new Date(Date.parse(view.price[2100].at) + 60_000).toISOString(),
  };
  const { container } = show(view);
  await screen.findByText("Chart 3 — STH supply in loss (%)");
  expect(moves(pathOf(chart(container, "loss"), "path.wh-seller-price"))).toBe(
    3,
  );
});

it("draws the Extreme and Warning lines and omits them when a level is missing", async () => {
  const { container, unmount } = show(pressureSample());
  await screen.findByText("Chart 3 — STH supply in loss (%)");
  for (const name of ["loss", "share", "supply"] as const) {
    expect(
      chart(container, name).querySelectorAll("line.wh-seller-extreme-line"),
    ).toHaveLength(1);
    expect(
      chart(container, name).querySelectorAll("line.wh-seller-warning-line"),
    ).toHaveLength(1);
  }
  unmount();

  const view = pressureSample();
  view.loss_levels = null;
  view.share_levels = { p95: null, p75: null, n: 0 };
  const second = show(view);
  await screen.findByText("Chart 3 — STH supply in loss (%)");
  for (const name of ["loss", "share"] as const) {
    const panel = chart(second.container, name);
    expect(panel.querySelector("line.wh-seller-extreme-line")).toBeNull();
    expect(panel.querySelector("line.wh-seller-warning-line")).toBeNull();
    expect(panel.querySelector(".wh-seller-extreme")?.textContent).toBe(
      "Unavailable",
    );
    expect(panel.querySelector(".wh-seller-warning")?.textContent).toBe(
      "Unavailable",
    );
    expect(panel.querySelector(".wh-seller-head")?.textContent).not.toMatch(
      /0\.0|\$0/,
    );
  }
  expect(
    chart(second.container, "supply").querySelector(
      "line.wh-seller-extreme-line",
    ),
  ).not.toBeNull();
});

it("marks the forming hour on the last point and in the header line", async () => {
  const view = pressureSample();
  const { container } = show(view);
  expect(
    await screen.findByText(
      "Resolution 1h · Data 2026-10-16 08:00 UTC · Source Bitcoin Research Kit",
    ),
  ).toBeTruthy();
  expect(screen.getByText(/includes the forming hour/)).toBeTruthy();
  for (const name of ["loss", "share", "supply"] as const) {
    const forming = chart(container, name).querySelectorAll(
      '[data-forming="true"]',
    );
    expect(forming).toHaveLength(1);
    expect(forming[0].getAttribute("data-at")).toBe(view.last_at);
  }
});

it("shows no forming marker once the last hour is closed", async () => {
  const { container } = show({ ...pressureSample(), forming_at: null });
  await screen.findByText(/Resolution 1h/);
  expect(screen.queryByText(/includes the forming hour/)).toBeNull();
  expect(container.querySelector('[data-forming="true"]')).toBeNull();
});

it("marks only the point at the forming time, not the last point of a lagging series", async () => {
  const view = pressureSample();
  // the share series has no row for the forming hour (its denominator was not positive)
  view.share = view.share.slice(0, -1);
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  expect(
    chart(container, "share").querySelector('[data-forming="true"]'),
  ).toBeNull();
  expect(
    chart(container, "loss").querySelectorAll('[data-forming="true"]'),
  ).toHaveLength(1);
});

it("says the data is unavailable and why, with no chart", async () => {
  const { container } = show(unavailable(["brk_unavailable"]));
  expect(await screen.findByText("Seller pressure unavailable")).toBeTruthy();
  expect(screen.getByText("on-chain data source unavailable")).toBeTruthy();
  expect(container.querySelector("svg")).toBeNull();
  expect(container.querySelector("[data-chart]")).toBeNull();
  expect(container.textContent ?? "").not.toMatch(/\d/);
});

it("names the missing hour1 series", async () => {
  show(unavailable(["series_missing:hour1:price_close"]));
  expect(
    await screen.findByText("missing series hour1:price_close"),
  ).toBeTruthy();
});

it("shows a loading line and no number while the request is pending", () => {
  const { container } = show("pending");
  expect(screen.getByText("Loading seller pressure…")).toBeTruthy();
  expect(container.querySelector("svg")).toBeNull();
  expect(container.textContent ?? "").not.toMatch(/\d/);
});

it("shows the failure and never the earlier reading", async () => {
  const { container } = show(
    new Error("Python service unavailable"),
    pressureSample(),
  );
  expect(await screen.findByText("Seller pressure unavailable")).toBeTruthy();
  expect(screen.getByText("Python service unavailable")).toBeTruthy();
  expect(container.querySelector("svg")).toBeNull();
  expect(screen.queryByText(/Chart 1/)).toBeNull();
});

it("treats a failure with an empty message as a failure", async () => {
  const { container } = show(new Error(""), pressureSample());
  expect(await screen.findByText("Seller pressure unavailable")).toBeTruthy();
  expect(container.querySelector("svg")).toBeNull();
});

it.each([
  ["delayed", "Data is delayed · data to 2026-10-16 08:00 UTC"],
  ["stale", "Data is stale · data to 2026-10-16 08:00 UTC"],
] as const)(
  "warns when the data is %s but keeps the charts",
  async (state, notice) => {
    const { container } = show({ ...pressureSample(), data_state: state });
    expect(await screen.findByText(notice)).toBeTruthy();
    expect(container.querySelectorAll("svg")).toHaveLength(3);
    // The hour that was forming then has long closed: it was partial, not forming now.
    expect(
      screen.getByText(/last hour was partial when computed/),
    ).toBeTruthy();
    expect(screen.queryByText(/includes the forming hour/)).toBeNull();
  },
);

it("names the failed QC checks in a warning line", async () => {
  const { container, unmount } = show({
    ...pressureSample(),
    qc: ["intraday_legs"],
  });
  const line = await screen.findByText(
    "QC 1 failed: intraday legs on every hour",
  );
  expect(line.className).toBe("wh-onchain-warn");
  expect(container.querySelectorAll("svg")).toHaveLength(3);
  unmount();

  show({ ...pressureSample(), qc: ["hour_gap", "sth_supply"] });
  expect(
    await screen.findByText(
      "QC 2 failed: no hourly gap over 2 hours, STH supply on every hour",
    ),
  ).toBeTruthy();
});

it("shows no QC line when every check passes", async () => {
  const { container } = show(pressureSample());
  await screen.findByText(/Resolution 1h/);
  expect(screen.queryByText(/QC/)).toBeNull();
  expect(container.querySelector(".wh-onchain-warn")).toBeNull();
});

it("shows no warning for fresh data", async () => {
  show(pressureSample());
  await screen.findByText(/Resolution 1h/);
  expect(screen.queryByText(/Data is (delayed|stale)/)).toBeNull();
  expect(screen.queryByRole("status")).toBeNull();
});

it("says when it is refreshing", async () => {
  show({ ...pressureSample(), refreshing: true });
  expect(await screen.findByRole("status")).toBeTruthy();
  expect(screen.getByText("Refreshing on-chain data…")).toBeTruthy();
});

it("shows a message instead of an empty chart when a series has no points", async () => {
  const view = pressureSample();
  view.share = [];
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  expect(chart(container, "share").querySelector("svg")).toBeNull();
  expect(
    within(chart(container, "share")).getByText("No data for this chart"),
  ).toBeTruthy();
  expect(chart(container, "loss").querySelector("svg")).not.toBeNull();
});

it("shows the price as unavailable when the latest hour has no price", async () => {
  const view = pressureSample();
  view.price = view.price.slice(0, -1);
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  expect(
    chart(container, "loss").querySelector(".wh-seller-legend")?.textContent,
  ).toContain("BTC/USD Unavailable");
});

it("keeps a tapped reading when the finger lifts and clears it when the mouse leaves", async () => {
  const { container } = show(pressureSample());
  await screen.findByText(/Resolution 1h/);
  const svg = chart(container, "share").querySelector("svg")!;
  const legend = () =>
    chart(container, "share").querySelector(".wh-seller-legend")?.textContent ??
    "";
  fireEvent.keyDown(svg, { key: "ArrowLeft" });
  expect(legend()).toContain("2026-10-16 07:00 UTC");
  fireEvent.pointerLeave(svg, { pointerType: "touch" });
  expect(legend()).toContain("2026-10-16 07:00 UTC");
  fireEvent.pointerLeave(svg, { pointerType: "mouse" });
  expect(legend()).toContain("Latest");
});

it("reads a point in UTC from the keyboard", async () => {
  const { container } = show(pressureSample());
  await screen.findByText(/Resolution 1h/);
  const svg = chart(container, "share").querySelector("svg")!;
  const legend = () =>
    chart(container, "share").querySelector(".wh-seller-legend")?.textContent ??
    "";
  expect(legend()).toContain("Latest");
  fireEvent.keyDown(svg, { key: "ArrowLeft" });
  expect(legend()).toContain("2026-10-16 07:00 UTC");
  expect(legend()).not.toContain("41.9%");
  fireEvent.keyDown(svg, { key: "ArrowLeft" });
  expect(legend()).toContain("2026-10-16 06:00 UTC");
  fireEvent.keyDown(svg, { key: "Escape" });
  expect(legend()).toContain("Latest");
  expect(legend()).toContain("41.9%");
});

it("queries under the shared key and refreshes every five minutes", async () => {
  const { client } = show(pressureSample());
  await screen.findByText(/Resolution 1h/);
  const query = client
    .getQueryCache()
    .find({ queryKey: ["wh", "onchain", "seller-pressure"] });
  expect(query).toBeTruthy();
  expect(query?.observers[0].options.refetchInterval).toBe(300000);
  await waitFor(() => expect(mocks.pressure).toHaveBeenCalledOnce());
});

it("formats chart 1 amounts with three significant digits, as d3 .3~s does", () => {
  for (const [value, shown] of [
    [37_600_000, "$37.6M"],
    [9_390_000, "$9.39M"],
    [85_200, "$85.2k"],
    [252_000, "$252k"],
    [17_900_000, "$17.9M"],
    [1_983_300, "$1.98M"],
    [8_540_500, "$8.54M"],
    [41_345_525, "$41.3M"],
    [10_050_150, "$10.1M"],
    [999, "$999"],
    // trailing zeros are dropped, and anything under 1 prints with two decimals
    [10_000_000, "$10M"],
    [1_500_000, "$1.5M"],
    [0, "$0.00"],
    // rounded to three digits before the unit is picked, so never "$1000k"
    [999_950, "$1M"],
    [999_500, "$1M"],
    [99_950, "$100k"],
  ] as const)
    expect(sigUsd(value)).toBe(shown);
});

it("formats axis amounts, percents and prices the way the plan fixes them", () => {
  expect(compactUsd(41_345_525, 1)).toBe("$41.3M");
  expect(compactUsd(10_050_150, 1)).toBe("$10.1M");
  // rounding up must not leave "1000.0K"
  expect(compactUsd(999_960, 1)).toBe("$1.0M");
  expect(compactUsd(0, 1)).toBe("$0.0");
  expect(percent(0.41893330324776934)).toBe("41.9%");
  expect(percent(0.5611976039771673)).toBe("56.1%");
  expect(usdPrice(100234.456)).toBe("$100,234.5");
  expect(usdPrice(100000)).toBe("$100,000.0");
});

it("has Chinese copy for every seller key and a different string from English", () => {
  const keys = Object.keys(messages.en).filter((key) =>
    key.startsWith("seller."),
  );
  expect(keys.length).toBeGreaterThan(20);
  for (const key of keys) {
    const zh = messages.zh[key as keyof typeof messages.zh];
    expect(zh.length).toBeGreaterThan(0);
  }
  expect(messages.zh["seller.loss.shows" as keyof typeof messages.zh]).not.toBe(
    messages.en["seller.loss.shows" as keyof typeof messages.en],
  );
});

// Reads one hour back from the latest on a chart's keyboard and returns its legend.
const readBack = (
  container: HTMLElement,
  name: "loss" | "share" | "supply",
) => {
  fireEvent.keyDown(chart(container, name).querySelector("svg")!, {
    key: "ArrowLeft",
  });
  return (
    chart(container, name).querySelector(".wh-seller-legend")?.textContent ?? ""
  );
};

it("draws an hour without a block as 0 and says so when it is read", async () => {
  // O3 keeps the hour: no flows, no share (0 / 0), supply and price carried over.
  const view = pressureSample();
  const hour = view.loss.length - 2;
  view.loss[hour] = { ...view.loss[hour], lth: 0, sth: 0, no_block: true };
  view.share[hour] = { ...view.share[hour], value: null, no_block: true };
  view.supply[hour] = {
    ...view.supply[hour - 1],
    at: view.supply[hour].at,
    no_block: true,
  };
  view.price[hour] = {
    ...view.price[hour - 1],
    at: view.price[hour].at,
    no_block: true,
  };
  const { container } = show({ ...view, rules: ["O3"] });
  await screen.findByText(/Resolution 1h/);

  // A 0 has no height, and an unknown share has no bar; the line and the price go on.
  for (const part of ["lth", "sth"])
    expect(
      chart(container, "loss").querySelectorAll(`rect.wh-seller-bar--${part}`),
    ).toHaveLength(719);
  expect(
    chart(container, "share").querySelectorAll("rect.wh-seller-bar"),
  ).toHaveLength(719);
  expect(moves(pathOf(chart(container, "supply"), "path.wh-seller-line"))).toBe(
    1,
  );
  expect(moves(pathOf(chart(container, "loss"), "path.wh-seller-price"))).toBe(
    1,
  );

  const loss = readBack(container, "loss");
  expect(loss).toContain("No block this hour");
  expect(loss).toContain("LTH loss $0.00");
  expect(loss).not.toContain("Series gap");
  const share = readBack(container, "share");
  expect(share).toContain("No block this hour");
  expect(share).toContain("STH loss share Unavailable");
  expect(share).not.toMatch(/0\.0%/);
  // The latest hour had a block: no note.
  fireEvent.keyDown(chart(container, "loss").querySelector("svg")!, {
    key: "Escape",
  });
  expect(chart(container, "loss").querySelector(".wh-seller-note")).toBeNull();
});

it("draws no bar or line for a gap and says so when it is read", async () => {
  const view = pressureSample();
  const hour = view.loss.length - 2;
  view.loss[hour] = { ...view.loss[hour], lth: null, gap: true };
  view.share[hour] = { ...view.share[hour], value: null, gap: true };
  view.supply[hour] = { ...view.supply[hour], value: null, gap: true };
  view.price[hour] = { ...view.price[hour], value: null, gap: true };
  const { container } = show({ ...view, rules: ["O3"] });
  await screen.findByText(/Resolution 1h/);

  // One unknown leg leaves the stack unknown: neither part is drawn, never as 0.
  for (const part of ["lth", "sth"])
    expect(
      chart(container, "loss").querySelectorAll(`rect.wh-seller-bar--${part}`),
    ).toHaveLength(719);
  expect(
    chart(container, "share").querySelectorAll("rect.wh-seller-bar"),
  ).toHaveLength(719);
  expect(moves(pathOf(chart(container, "supply"), "path.wh-seller-line"))).toBe(
    2,
  );
  expect(moves(pathOf(chart(container, "loss"), "path.wh-seller-price"))).toBe(
    2,
  );

  const loss = readBack(container, "loss");
  expect(loss).toContain("Series gap: value unavailable");
  expect(loss).toContain("LTH loss Unavailable");
  // The known leg still reads.
  expect(loss).toMatch(/STH loss \$\d/);
  expect(loss).toContain("BTC/USD Unavailable");
  expect(loss).not.toContain("No block");
  for (const name of ["share", "supply"] as const)
    expect(readBack(container, name)).toContain(
      "Series gap: value unavailable",
    );
});

it("keeps the axes when a span has no known value", async () => {
  const view = pressureSample();
  view.share = view.share.map((point) => ({
    ...point,
    value: null,
    gap: true,
  }));
  view.share_levels = { p95: null, p75: null, n: 0 };
  view.supply = view.supply.map((point) => ({
    ...point,
    value: null,
    gap: true,
  }));
  view.supply_levels = { p95: null, p75: null, n: 0 };
  const { container } = show({ ...view, rules: ["O3"] });
  await screen.findByText(/Resolution 1h/);
  for (const name of ["share", "supply"] as const) {
    const svg = chart(container, name).querySelector("svg")!;
    expect(svg.innerHTML).not.toMatch(/NaN|Infinity/);
    expect(svg.querySelector("rect.wh-seller-bar")).toBeNull();
    // The latest point is unknown, so it has no forming marker either.
    expect(svg.querySelector('circle[data-forming="true"]')).toBeNull();
  }
});

it("names the O3 hour check by the gap it fails on", async () => {
  show({ ...pressureSample(), rules: ["O3"], qc: ["hour_gap"] });
  expect(await screen.findByText("QC 1 failed: no missing hour")).toBeTruthy();
});

it("says in the header that the original v1 rules produced the charts", async () => {
  show(pressureSample());
  expect(await screen.findByText("Rules: original v1")).toBeTruthy();
  expect(
    screen.queryByText("Recomputing with the configured rules"),
  ).toBeNull();
});

it("lists the rules that produced the charts in the header", async () => {
  show({ ...pressureSample(), rules: ["O1", "O2", "O3"] });
  expect(
    await screen.findByText(
      "Rules: O1 closed data only · O2 rolling thresholds · O3 no dropped rows",
    ),
  ).toBeTruthy();
  expect(screen.queryByText("Rules: original v1")).toBeNull();
});

it("says in the header that the charts are being recomputed", async () => {
  show({ ...pressureSample(), rules: ["O1"], rules_pending: true });
  expect(await screen.findByText("Rules: O1 closed data only")).toBeTruthy();
  expect(
    screen.getByText("Recomputing with the configured rules"),
  ).toBeTruthy();
});

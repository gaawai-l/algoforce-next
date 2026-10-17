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
  closed_at: null,
  loss_run: null,
  share_run: null,
  supply_run: null,
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

// ---- O2 thresholds as a step line, the level and run, and O1's default reading ----

const SERIES = ["loss", "share", "supply"] as const;
type Series = (typeof SERIES)[number];
type Level = "extreme" | "warning" | "none" | null;
interface Rolling {
  p95: number | null;
  p75: number | null;
  level?: Level;
}

// An O2 view: every point carries its own hour's thresholds. A chart-1 amount is in dollars, the
// other two are fractions, so the callback gets the series to size its thresholds.
function rolled(
  rules: SellerPressureView["rules"],
  thresholds: (index: number, name: Series) => Rolling,
): SellerPressureView {
  const view = pressureSample();
  const patch = (index: number, name: Series) => {
    const { p95, p75, level = null } = thresholds(index, name);
    return { p95, p75, level };
  };
  view.loss = view.loss.map((p, i) => ({ ...p, ...patch(i, "loss") }));
  view.share = view.share.map((p, i) => ({ ...p, ...patch(i, "share") }));
  view.supply = view.supply.map((p, i) => ({ ...p, ...patch(i, "supply") }));
  return { ...view, rules };
}
const unit = (name: Series) => (name === "loss" ? 10_000_000 : 0.1);

// The sample has 2200 hours and every chart opens on the last 720, rows 1480 to 2199. At the
// default width the plot is 610 wide from x = 52, so one hour is 610 / 720 wide.
const FIRST = 1480;
const SLOT = 610 / 720;
const numbers = (d: string, command: string) =>
  [...d.matchAll(new RegExp(`${command}([\\d.]+)`, "g"))].map((m) =>
    Number(m[1]),
  );
const startY = (d: string) => Number(/^M[\d.]+,([\d.]+)/.exec(d)![1]);

it("draws each threshold as a step line that follows the hour it belongs to", async () => {
  const view = rolled(["O2"], (i, name) => ({
    // The extreme line steps up once, in the middle of the window; the warning line never moves.
    p95: (i < 1900 ? 4 : 5) * unit(name),
    p75: 2 * unit(name),
  }));
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  for (const name of SERIES) {
    const panel = chart(container, name);
    // The rolling thresholds replace the flat lines the header levels would draw.
    expect(panel.querySelector("line.wh-seller-extreme-line")).toBeNull();
    expect(panel.querySelector("line.wh-seller-warning-line")).toBeNull();
    const extreme = pathOf(panel, "path.wh-seller-extreme-line");
    const warning = pathOf(panel, "path.wh-seller-warning-line");
    expect(moves(extreme)).toBe(1);
    expect(moves(warning)).toBe(1);
    // One step, up (a smaller y), at the hour whose threshold changed; the warning line is flat.
    expect(numbers(extreme, "V")).toHaveLength(1);
    expect(numbers(warning, "V")).toHaveLength(0);
    expect(numbers(extreme, "V")[0]).toBeLessThan(startY(extreme));
    expect(startY(extreme)).toBeLessThan(startY(warning));
    // The line covers the first slot of the window to the last one, edge to edge.
    expect(extreme.startsWith("M52,")).toBe(true);
    expect(numbers(extreme, "H").at(-1)).toBeCloseTo(662, 1);
    expect(numbers(warning, "H").at(-1)).toBeCloseTo(662, 1);
  }
});

it("redraws the step lines on the 7d span, one 168th of the plot per hour", async () => {
  const view = rolled(["O2"], (i, name) => ({
    p95: (i < 2100 ? 4 : 5) * unit(name),
    p75: 2 * unit(name),
  }));
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  for (const name of SERIES) {
    const panel = chart(container, name);
    fireEvent.click(within(panel).getByRole("button", { name: "7d" }));
    // Rows 2032 to 2199: the first slot starts at the left edge, each one is 610 / 168 wide and
    // the last ends at the right edge, 52 + 610.
    const slot = 610 / 168;
    for (const key of ["extreme", "warning"] as const) {
      const d = pathOf(panel, `path.wh-seller-${key}-line`);
      expect(moves(d)).toBe(1);
      expect(d.startsWith("M52,")).toBe(true);
      const ends = numbers(d, "H");
      expect(ends).toHaveLength(168);
      expect(ends[0]).toBeCloseTo(52 + slot, 1);
      expect(ends.at(-1)).toBeCloseTo(662, 1);
    }
    // The extreme line steps up where hour 2100 begins.
    const extreme = pathOf(panel, "path.wh-seller-extreme-line");
    const step = extreme.indexOf("V");
    expect(numbers(extreme.slice(0, step), "H").at(-1)).toBeCloseTo(
      52 + (2100 - 2032) * slot,
      1,
    );
  }
});

it("breaks a step line where the threshold is null, at the left edge and in the middle", async () => {
  const view = rolled(["O2"], (i, name) => ({
    // Fewer than 168 samples at the window's left edge, and a short cut in the middle.
    p95: i < FIRST + 100 || (i >= 1700 && i < 1710) ? null : 4 * unit(name),
    p75: 2 * unit(name),
  }));
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  for (const name of SERIES) {
    const panel = chart(container, name);
    const extreme = pathOf(panel, "path.wh-seller-extreme-line");
    // Two pieces: the line neither starts at the left edge nor crosses the cut.
    expect(moves(extreme)).toBe(2);
    const starts = [...extreme.matchAll(/M([\d.]+),/g)].map((m) =>
      Number(m[1]),
    );
    expect(starts[0]).toBeCloseTo(52 + 100 * SLOT, 1);
    expect(starts[1]).toBeCloseTo(52 + (1710 - FIRST) * SLOT, 1);
    const firstEnds = numbers(extreme.split("M")[1], "H").at(-1)!;
    expect(firstEnds).toBeCloseTo(52 + (1700 - FIRST) * SLOT, 1);
    // The warning line has all of its thresholds.
    expect(moves(pathOf(panel, "path.wh-seller-warning-line"))).toBe(1);
  }
});

it("draws a single known hour between two nulls and breaks at a missing row", async () => {
  const view = rolled(["O2"], (i, name) => ({
    p95: i === 1800 ? 4 * unit(name) : null,
    p75: 2 * unit(name),
  }));
  // Chart 3 also lost the row of hour 2000, so its warning line is cut there.
  view.supply = without(view.supply, 2000);
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  const alone = pathOf(chart(container, "loss"), "path.wh-seller-extreme-line");
  expect(moves(alone)).toBe(1);
  expect(
    numbers(alone, "H")[0] - Number(/^M([\d.]+),/.exec(alone)![1]),
  ).toBeCloseTo(SLOT, 1);
  expect(
    moves(pathOf(chart(container, "supply"), "path.wh-seller-warning-line")),
  ).toBe(2);
  expect(
    moves(pathOf(chart(container, "loss"), "path.wh-seller-warning-line")),
  ).toBe(1);
});

it("draws no threshold line and no NaN when every threshold is null", async () => {
  const view = rolled(["O2"], () => ({ p95: null, p75: null }));
  view.loss_levels = { p95: null, p75: null, n: 0 };
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  for (const name of SERIES) {
    const panel = chart(container, name);
    expect(panel.querySelector(".wh-seller-extreme-line")).toBeNull();
    expect(panel.querySelector(".wh-seller-warning-line")).toBeNull();
    expect(panel.querySelector("svg")!.innerHTML).not.toMatch(/NaN|Infinity/);
  }
});

it("keeps flat threshold lines from the header levels without O2", async () => {
  const { container } = show(pressureSample());
  await screen.findByText(/Resolution 1h/);
  for (const name of SERIES) {
    const panel = chart(container, name);
    expect(panel.querySelectorAll("line.wh-seller-extreme-line")).toHaveLength(
      1,
    );
    expect(panel.querySelector("path.wh-seller-extreme-line")).toBeNull();
    expect(panel.querySelector("path.wh-seller-warning-line")).toBeNull();
    // Nothing about a level or a run is shown when the thresholds do not roll.
    expect(panel.querySelector(".wh-seller-reading")).toBeNull();
  }
});

const reading = (container: HTMLElement, name: Series) =>
  chart(container, name).querySelector(".wh-seller-reading")?.textContent;

it("shows the level and the run of the current reading in each header", async () => {
  const view = rolled(["O2"], (_, name) => ({
    p95: 4 * unit(name),
    p75: 2 * unit(name),
  }));
  view.loss[view.loss.length - 1].level = "warning";
  view.share[view.share.length - 1].level = "extreme";
  view.supply[view.supply.length - 1].level = "none";
  view.loss_run = 5;
  view.share_run = 12;
  view.supply_run = 0;
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  expect(reading(container, "loss")).toBe("Level Warning · run 5 h");
  expect(reading(container, "share")).toBe("Level Extreme · run 12 h");
  // Below the warning line is a level of its own, and a run of 0 is a real count.
  expect(reading(container, "supply")).toBe("Level Normal · run 0 h");
  // The level takes the colour of its threshold line.
  const level = (name: Series) =>
    chart(container, name).querySelector<HTMLElement>(".wh-seller-level")!;
  expect(level("loss").className).toContain("wh-seller-warning");
  expect(level("share").className).toContain("wh-seller-extreme");
  expect(level("supply").className).not.toMatch(/wh-seller-(warning|extreme)/);
  expect(level("loss").getAttribute("data-level")).toBe("warning");
  // The thresholds beside it are the header levels, as before.
  expect(
    chart(container, "loss").querySelector(".wh-seller-extreme")?.textContent,
  ).toBe("$41.3M");
});

it("shows a dash, not 0, when the current reading has no level or run", async () => {
  // Thresholds are null while fewer than 168 hours exist, so the level and the run are too.
  const view = rolled(["O2"], () => ({ p95: null, p75: null }));
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  for (const name of SERIES)
    expect(reading(container, name)).toBe("Level — · run —");

  // One chart with a level but no run (cannot happen, yet a missing number is never read as 0).
  const second = rolled(["O2"], (_, name) => ({
    p95: 4 * unit(name),
    p75: 2 * unit(name),
    level: "warning",
  }));
  second.loss_run = null;
  second.share_run = 3;
  cleanup();
  const again = show(second);
  await screen.findByText(/Resolution 1h/);
  expect(reading(again.container, "loss")).toBe("Level Warning · run —");
  expect(reading(again.container, "share")).toBe("Level Warning · run 3 h");
});

it("reads the level of the closed row under O1, not the forming one", async () => {
  const view = rolled(["O1", "O2"], (_, name) => ({
    p95: 4 * unit(name),
    p75: 2 * unit(name),
    level: "none",
  }));
  const closed = view.loss.length - 2;
  // The forming hour has no level; the hour before it closed at extreme.
  for (const name of SERIES) view[name][view.loss.length - 1].level = null;
  view.loss[closed].level = "extreme";
  view.loss_run = 2;
  view.closed_at = view.loss[closed].at;
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  expect(reading(container, "loss")).toBe("Level Extreme · run 2 h");
});

it("has the level and run copy in both languages", () => {
  for (const key of [
    "seller.level",
    "seller.levelNone",
    "seller.run",
    "seller.runHours",
    "seller.latestClosed",
  ] as const) {
    expect(messages.en[key].length).toBeGreaterThan(0);
    expect(messages.zh[key]).not.toBe(messages.en[key]);
  }
});

// Under O1 the legend opens on the newest closed row; the newest row may still be forming.
function closedView() {
  const view = pressureSample();
  const closed = view.loss.length - 2;
  view.share[closed] = { ...view.share[closed], value: 0.3333 };
  view.loss[closed] = { ...view.loss[closed], lth: 1_000_000, sth: 2_000_000 };
  return { ...view, rules: ["O1" as const], closed_at: view.loss[closed].at };
}
const legendOf = (container: HTMLElement, name: Series) =>
  chart(container, name).querySelector(".wh-seller-legend")?.textContent ?? "";

it("opens the legend on the closed row under O1 and returns to it", async () => {
  const { container } = show(closedView());
  await screen.findByText(/Resolution 1h/);
  const share = () => legendOf(container, "share");
  expect(share()).toContain("Latest closed · 2026-10-16 07:00 UTC");
  expect(share()).toContain("33.3%");
  expect(share()).not.toContain("41.9%");
  expect(legendOf(container, "loss")).toContain("LTH loss $1M");
  // The keys start from the closed row, can reach the forming one, and Escape comes back.
  const svg = chart(container, "share").querySelector("svg")!;
  fireEvent.keyDown(svg, { key: "ArrowLeft" });
  expect(share()).toContain("2026-10-16 06:00 UTC");
  fireEvent.keyDown(svg, { key: "Escape" });
  expect(share()).toContain("Latest closed · 2026-10-16 07:00 UTC");
  fireEvent.keyDown(svg, { key: "ArrowRight" });
  expect(share()).toContain("2026-10-16 08:00 UTC");
  expect(share()).toContain("41.9%");
  fireEvent.keyDown(svg, { key: "End" });
  expect(share()).toContain("Latest closed · 2026-10-16 07:00 UTC");
  // The forming hour is still drawn.
  expect(
    chart(container, "share").querySelectorAll('[data-forming="true"]'),
  ).toHaveLength(1);
});

it("opens the legend on the last row without O1, even when closed_at is set", async () => {
  const { container } = show({ ...closedView(), rules: [] });
  await screen.findByText(/Resolution 1h/);
  const share = legendOf(container, "share");
  expect(share).toContain("Latest · 2026-10-16 08:00 UTC");
  expect(share).toContain("41.9%");
  expect(share).not.toContain("Latest closed");
});

it("opens on the newest closed row when the closed hour has no row on that chart", async () => {
  const view = closedView();
  // A share whose denominator was not positive in the closed hour has no row there; the last row
  // is still forming, so the legend opens on the hour before the closed one.
  view.share = view.share.filter((p) => p.at !== view.closed_at);
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  const share = () => legendOf(container, "share");
  expect(share()).toContain("Latest closed · 2026-10-16 06:00 UTC");
  expect(share()).not.toContain("41.9%");
  expect(legendOf(container, "loss")).toContain(
    "Latest closed · 2026-10-16 07:00 UTC",
  );
  // The keys start from it, and Escape comes back to it.
  const svg = chart(container, "share").querySelector("svg")!;
  fireEvent.keyDown(svg, { key: "ArrowRight" });
  expect(share()).toContain("2026-10-16 08:00 UTC");
  fireEvent.keyDown(svg, { key: "Escape" });
  expect(share()).toContain("Latest closed · 2026-10-16 06:00 UTC");
});

it("says that Escape returns to the latest closed hour only when the legend rests on one", async () => {
  const label = (container: HTMLElement) =>
    chart(container, "share").querySelector("svg")!.getAttribute("aria-label");
  const closed = show(closedView());
  await screen.findByText(/Resolution 1h/);
  expect(label(closed.container)).toBe(
    "Chart 2 — STH realized loss as a share of the sell side (%). Use the left and right arrow keys to read one hour; Escape returns to the latest closed hour.",
  );
  cleanup();
  // Without O1, and under O1 before any hour has closed, it returns to the last row.
  for (const view of [
    { ...closedView(), rules: [] },
    { ...closedView(), closed_at: null },
  ]) {
    const { container } = show(view);
    await screen.findByText(/Resolution 1h/);
    expect(label(container)).toBe(
      "Chart 2 — STH realized loss as a share of the sell side (%). Use the left and right arrow keys to read one hour; Escape returns to the latest.",
    );
    cleanup();
  }
  expect(messages.zh["seller.ariaClosed"]).toBe(
    "{{title}}。用左右方向键逐小时读取；按 Esc 回到最近已收盘的小时。",
  );
});

it("opens the legend on the last row under O1 when nothing has closed", async () => {
  const { container } = show({
    ...pressureSample(),
    rules: ["O1"],
    closed_at: null,
  });
  await screen.findByText(/Resolution 1h/);
  expect(legendOf(container, "share")).toContain(
    "Latest · 2026-10-16 08:00 UTC",
  );
});

it("draws no forming marker at a null value on the bar and stacked charts", async () => {
  // The forming hour's share is unknown, and so is one leg of its loss.
  const view = pressureSample();
  view.share[view.share.length - 1] = {
    ...view.share[view.share.length - 1],
    value: null,
    gap: true,
  };
  view.loss[view.loss.length - 1] = {
    ...view.loss[view.loss.length - 1],
    sth: null,
    gap: true,
  };
  const { container } = show({ ...view, rules: ["O3"] });
  await screen.findByText(/Resolution 1h/);
  expect(
    chart(container, "share").querySelector('[data-forming="true"]'),
  ).toBeNull();
  expect(
    chart(container, "loss").querySelector('[data-forming="true"]'),
  ).toBeNull();
  // The line chart already drew none, and a known value still gets its marker.
  expect(
    chart(container, "supply").querySelectorAll('[data-forming="true"]'),
  ).toHaveLength(1);
});

it("still marks a forming bar whose value is 0", async () => {
  const view = pressureSample();
  view.share[view.share.length - 1] = {
    ...view.share[view.share.length - 1],
    value: 0,
  };
  const { container } = show(view);
  await screen.findByText(/Resolution 1h/);
  expect(
    chart(container, "share").querySelectorAll('rect[data-forming="true"]'),
  ).toHaveLength(1);
});

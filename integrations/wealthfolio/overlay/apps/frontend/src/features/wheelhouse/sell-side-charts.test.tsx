import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { sellSideSchema, type SellSideView } from "./onchain-contract";
import expected from "./sell-side-expected.json";
import raw from "./sell-side-sample.json";
import { SellSideCharts } from "./sell-side-charts";

const mocks = vi.hoisted(() => ({ sellSide: vi.fn() }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getSellSide: mocks.sellSide,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const sample = sellSideSchema.parse(raw);
const LEG_NAMES = ["LTH profit", "LTH loss", "STH profit", "STH loss"];
// Every leg of one measure set to the same column.
const filled = (values: number[]): SellSideView["pnl"] => ({
  lth_profit: values,
  lth_loss: values,
  sth_profit: values,
  sth_loss: values,
  sth_profit_x1: values,
  sth_loss_x1: values,
  sth_profit_x24: values,
  sth_loss_x24: values,
});

function show(view: SellSideView | Error) {
  if (view instanceof Error) mocks.sellSide.mockRejectedValue(view);
  else mocks.sellSide.mockResolvedValue(view);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SellSideCharts />
    </QueryClientProvider>,
  );
}

const panel = (key: "a" | "b") =>
  document.querySelector<HTMLElement>(`[data-chart="sellside-${key}"]`)!;
// The legend values of the four legs, in stacking order.
const legend = (key: "a" | "b") =>
  LEG_NAMES.map(
    (name) =>
      within(panel(key))
        .getByRole("button", { name: new RegExp(`^${name} `) })
        .querySelector("b")!.textContent,
  );
const caseFor = (smoothing: number, shown = ["LP", "LL", "SP", "SL"]) =>
  expected.cases.find(
    (c) =>
      c.measure === "pnl" &&
      c.exclude === "x24" &&
      c.smoothing === smoothing &&
      c.span === 720 &&
      c.shown.join() === shown.join(),
  )!;

it("draws both charts with the original's default readings", async () => {
  show(sample);
  await screen.findByText("Chart 1 — Sell Side Breakdown by LTH & STH · Relative (A)");
  expect(
    screen.getByText("Chart 1 — Sell Side Breakdown by LTH & STH · Absolute (B)"),
  ).toBeTruthy();
  const defaults = caseFor(24);
  expect(legend("a")).toEqual(defaults.legendA);
  expect(legend("b")).toEqual(defaults.legendB);
  for (const key of ["a", "b"] as const) {
    expect(within(panel(key)).getByText(defaults.foot)).toBeTruthy();
    expect(panel(key).querySelector("svg")!.getAttribute("data-points")).toBe("720");
  }
  // The newest hour was still forming when the service derived it.
  expect(panel("a").querySelector('[data-forming="true"]')).not.toBeNull();
  expect(screen.getByText(/includes the forming hour/)).toBeTruthy();
});

it("drives both charts from either chart's controls", async () => {
  show(sample);
  await screen.findByText("Chart 1 — Sell Side Breakdown by LTH & STH · Relative (A)");
  fireEvent.click(within(panel("b")).getByRole("button", { name: "1h" }));
  for (const key of ["a", "b"] as const)
    expect(
      within(panel(key)).getByRole("button", { name: "1h" }).getAttribute("aria-pressed"),
    ).toBe("true");
  const smoothed = caseFor(1);
  expect(legend("a")).toEqual(smoothed.legendA);
  expect(legend("b")).toEqual(smoothed.legendB);
  fireEvent.click(within(panel("a")).getByRole("button", { name: "7d" }));
  expect(panel("b").querySelector("svg")!.getAttribute("data-points")).toBe("168");
});

it("shares out over the legs left when one is hidden, and says so on A only", async () => {
  show(sample);
  await screen.findByText("Chart 1 — Sell Side Breakdown by LTH & STH · Relative (A)");
  fireEvent.click(within(panel("b")).getByRole("button", { name: /^LTH profit / }));
  const hidden = caseFor(24, ["LL", "SP", "SL"]);
  expect(legend("a")).toEqual(hidden.legendA);
  expect(legend("b")).toEqual(hidden.legendB);
  expect(
    within(panel("a")).getByText("shares of the 3 visible legs, not the full sell side"),
  ).toBeTruthy();
  expect(within(panel("b")).queryByText(/visible leg/)).toBeNull();
  expect(within(panel("a")).getByText(hidden.foot)).toBeTruthy();
});

it("never hides the last leg shown", async () => {
  show(sample);
  await screen.findByText("Chart 1 — Sell Side Breakdown by LTH & STH · Relative (A)");
  for (const name of ["LTH profit", "LTH loss", "STH profit", "STH loss"])
    fireEvent.click(within(panel("a")).getByRole("button", { name: new RegExp(`^${name} `) }));
  expect(legend("a")).toEqual(["off", "off", "off", "100.0%"]);
  expect(
    within(panel("a")).getByText("shares of the 1 visible leg, not the full sell side"),
  ).toBeTruthy();
});

it("says the data is unavailable instead of drawing zeros", async () => {
  show({
    ...sample,
    data_state: "unavailable",
    reasons: ["series_missing:hour1:utxos_1h_to_1d_old_realized_loss_cumulative"],
    forming_at: null,
    last_at: null,
    at: [],
    price: [],
    pnl: filled([]),
    volb: filled([]),
    volu: filled([]),
    xgap: null,
  });
  expect(await screen.findByText("Sell side unavailable")).toBeTruthy();
  expect(document.querySelector("svg")).toBeNull();
});

it("shows no chart for a choice that leaves no row", async () => {
  show({ ...sample, pnl: filled(sample.at.map(() => 0)) });
  expect(await screen.findAllByText("No data for this chart")).toHaveLength(2);
  expect(document.querySelector("svg")).toBeNull();
});

it("puts a failed request ahead of the charts", async () => {
  show(new Error("Python service unavailable (HTTP 503). No simulated fallback was used."));
  expect(await screen.findByText("Sell side unavailable")).toBeTruthy();
  expect(screen.getByText(/HTTP 503/)).toBeTruthy();
});

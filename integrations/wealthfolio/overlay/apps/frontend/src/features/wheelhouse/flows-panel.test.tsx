import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, onTestFinished, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { FlowsPanel } from "./flows-panel";
import ageCohortsRaw from "./age-cohorts-sample.json";
import costBasisHistoryRaw from "./cost-basis-history-sample.json";
import costFlowRaw from "./cost-flow-sample.json";
import {
  ageCohortsSchema,
  costBasisHistorySchema,
  costFlowSchema,
  pressureSample,
  sellSideSchema,
  sizeCohortsSchema,
} from "./onchain-contract";
import sellSideRaw from "./sell-side-sample.json";
import sizeCohortsRaw from "./size-cohorts-sample.json";
import { perpStatesSample } from "./perps-contract";
import type { Stream } from "./client";

const mocks = vi.hoisted(() => ({
  pressure: vi.fn(),
  sellSide: vi.fn(),
  ageCohorts: vi.fn(),
  costFlow: vi.fn(),
  // Chart 8 sits under Charts 3 and 4; it waits unless a test answers it.
  costBasisHistory: vi.fn((_span: string): Promise<unknown> => new Promise(() => {})),
  sizes: vi.fn(),
  perpStates: vi.fn(),
  perpStatus: vi.fn(),
}));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getSellerPressure: mocks.pressure,
  getSellSide: mocks.sellSide,
  getAgeCohorts: mocks.ageCohorts,
  getCostFlow: mocks.costFlow,
  getCostBasisHistory: mocks.costBasisHistory,
  getSizeCohorts: mocks.sizes,
  getPerpStates: mocks.perpStates,
  getPerpStatus: mocks.perpStatus,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const chartOne = "Chart 1 — Total realized loss by cohorts (USD)";
const perpTable = "Table 1 — Perp states";
const sellSideA = "Chart 1 — Sell Side Breakdown by LTH & STH · Relative (A)";

function Where() {
  return <output data-testid="where">{useLocation().search}</output>;
}

function show(search = "", symbol: Stream["symbol"] = "BTCUSDT") {
  mocks.perpStates.mockResolvedValue(perpStatesSample());
  mocks.perpStatus.mockReturnValue(new Promise(() => {}));
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/market-intelligence${search}`]}>
        <FlowsPanel symbol={symbol} />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("shows the seller pressure charts by default", async () => {
  mocks.pressure.mockResolvedValue(pressureSample());
  show();
  expect(await screen.findByText(chartOne)).toBeTruthy();
  expect(
    screen.queryByText("Seller pressure is not implemented yet"),
  ).toBeNull();
  expect(screen.queryByText(perpTable)).toBeNull();
  expect(mocks.perpStates).not.toHaveBeenCalled();
  expect(
    screen
      .getByRole("button", { name: "Seller pressure" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  expect(
    screen
      .getByRole("button", { name: "Perp states" })
      .getAttribute("aria-pressed"),
  ).toBe("false");
});

it("shows the perp states view for flow=perp and does not query seller pressure", async () => {
  show("?flow=perp");
  expect(await screen.findByText(perpTable)).toBeTruthy();
  expect(screen.getByText("Parameters")).toBeTruthy();
  expect(mocks.perpStates).toHaveBeenCalledWith(
    "all",
    "4h",
    expect.any(AbortSignal),
  );
  expect(screen.queryByText(/Not connected/)).toBeNull();
  expect(screen.queryByText(chartOne)).toBeNull();
  expect(screen.queryByText(/not implemented yet/)).toBeNull();
  expect(mocks.pressure).not.toHaveBeenCalled();
  expect(
    screen
      .getByRole("button", { name: "Perp states" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});

it("shows the sell side for flow=sellside and queries nothing else", async () => {
  mocks.sellSide.mockResolvedValue(sellSideSchema.parse(sellSideRaw));
  mocks.ageCohorts.mockResolvedValue(ageCohortsSchema.parse(ageCohortsRaw));
  show("?flow=sellside");
  expect(await screen.findByText(sellSideA)).toBeTruthy();
  // Chart 2 follows Charts 1A and 1B.
  expect(
    await screen.findByText("Chart 2 — Sell Side Breakdown by All Age Cohorts"),
  ).toBeTruthy();
  expect(mocks.pressure).not.toHaveBeenCalled();
  expect(mocks.perpStates).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "Sell side" }).getAttribute("aria-pressed"),
  ).toBe("true");
});

it("offers the flows in order and opens Cost basis from the URL", async () => {
  mocks.costFlow.mockResolvedValue(costFlowSchema.parse(costFlowRaw));
  show("?flow=costbasis");
  expect(
    await screen.findByText("Chart 3 — Buy & Sell Side By Cost Basis"),
  ).toBeTruthy();
  expect(
    within(screen.getByRole("group", { name: "Flows view" }))
      .getAllByRole("button")
      .map((button) => button.textContent),
  ).toEqual(["Seller pressure", "Sell side", "Cost basis", "Size cohorts", "Perp states"]);
  expect(
    screen.getByRole("button", { name: "Cost basis" }).getAttribute("aria-pressed"),
  ).toBe("true");
  expect(mocks.costFlow).toHaveBeenCalledTimes(1);
  for (const other of [
    mocks.pressure,
    mocks.sellSide,
    mocks.ageCohorts,
    mocks.sizes,
    mocks.perpStates,
    mocks.perpStatus,
  ])
    expect(other).not.toHaveBeenCalled();
});

it("shows the size cohorts for flow=sizes and queries nothing else", async () => {
  mocks.sizes.mockResolvedValue(sizeCohortsSchema.parse(sizeCohortsRaw));
  show("?flow=sizes");
  expect(
    await screen.findByText("Chart 5 — Net Supply Change By Size Cohorts"),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Size cohorts" }).getAttribute("aria-pressed"),
  ).toBe("true");
  expect(mocks.sizes).toHaveBeenCalledTimes(1);
  for (const other of [
    mocks.pressure,
    mocks.sellSide,
    mocks.ageCohorts,
    mocks.costFlow,
    mocks.perpStates,
    mocks.perpStatus,
  ])
    expect(other).not.toHaveBeenCalled();
  const names = within(screen.getByRole("group", { name: "Flows view" }))
    .getAllByRole("button")
    .map((button) => button.textContent);
  expect(names).toHaveLength(5);
  expect(names.indexOf("Size cohorts")).toBe(names.indexOf("Perp states") - 1);
});

it("falls back to seller pressure for an unknown flow value", async () => {
  mocks.pressure.mockResolvedValue(pressureSample());
  show("?flow=nonsense");
  expect(await screen.findByText(chartOne)).toBeTruthy();
});

it("invents no number before the seller pressure answer arrives", () => {
  mocks.pressure.mockReturnValue(new Promise(() => {}));
  const { container } = show();
  expect(screen.getByText("Loading seller pressure…")).toBeTruthy();
  expect(container.textContent ?? "").not.toMatch(/\d/);
});

it("writes the chosen view to the flow parameter and keeps other parameters", async () => {
  mocks.pressure.mockResolvedValue(pressureSample());
  show("?symbol=BTCUSDT&method=flows");
  await screen.findByText(chartOne);
  fireEvent.click(screen.getByRole("button", { name: "Perp states" }));
  const params = new URLSearchParams(
    screen.getByTestId("where").textContent ?? "",
  );
  expect(params.get("flow")).toBe("perp");
  expect(params.get("method")).toBe("flows");
  expect(params.get("symbol")).toBe("BTCUSDT");
  expect(await screen.findByText(perpTable)).toBeTruthy();
  expect(screen.queryByText(chartOne)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Seller pressure" }));
  expect(
    new URLSearchParams(screen.getByTestId("where").textContent ?? "").get(
      "flow",
    ),
  ).toBe("seller");
  expect(await screen.findByText(chartOne)).toBeTruthy();
});

it.each(["ETHUSDT", "MUUSDT"] as const)(
  "says flows are BTC only for %s, shows no view switch and never queries seller pressure",
  (symbol) => {
    const { container } = show("?flow=perp", symbol);
    expect(screen.getByText("Flows are BTC only")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText(/Not connected/)).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent ?? "").not.toMatch(/\d/);
    expect(mocks.pressure).not.toHaveBeenCalled();
    expect(mocks.sellSide).not.toHaveBeenCalled();
    expect(mocks.ageCohorts).not.toHaveBeenCalled();
    expect(mocks.costFlow).not.toHaveBeenCalled();
    expect(mocks.sizes).not.toHaveBeenCalled();
    expect(mocks.perpStates).not.toHaveBeenCalled();
    expect(mocks.perpStatus).not.toHaveBeenCalled();
  },
);

it.each(["ETHUSDT", "MUUSDT"] as const)(
  "does not show seller pressure for %s even on the default view",
  (symbol) => {
    show("", symbol);
    expect(screen.getByText("Flows are BTC only")).toBeTruthy();
    expect(screen.queryByText(chartOne)).toBeNull();
    expect(mocks.pressure).not.toHaveBeenCalled();
  },
);

it("draws Chart 8 under Charts 3 and 4 in Cost basis", async () => {
  const context = vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  onTestFinished(() => context.mockRestore());
  mocks.costFlow.mockResolvedValue(costFlowSchema.parse(costFlowRaw));
  mocks.costBasisHistory.mockResolvedValueOnce(
    costBasisHistorySchema.parse(costBasisHistoryRaw),
  );
  const { container } = show("?flow=costbasis");
  expect(
    await screen.findByText("Chart 8 — Cost Basis Distribution, All Coins"),
  ).toBeTruthy();
  await screen.findByText("Chart 4 — Buy & Sell Side By Cost Basis · Age Breakdown");
  const charts = [
    ...container.querySelectorAll(".wh-flows section[data-chart]"),
  ].map((section) => section.getAttribute("data-chart"));
  expect(charts.slice(-2)).toEqual(["costflow-4", "cost-basis-history"]);
  expect(mocks.costBasisHistory).toHaveBeenCalledTimes(1);
  expect(mocks.costBasisHistory.mock.calls[0][0]).toBe("365");
});

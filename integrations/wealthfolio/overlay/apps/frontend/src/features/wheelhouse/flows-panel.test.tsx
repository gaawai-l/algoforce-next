import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { FlowsPanel } from "./flows-panel";
import { pressureSample } from "./onchain-contract";
import type { Stream } from "./client";

const mocks = vi.hoisted(() => ({ pressure: vi.fn() }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getSellerPressure: mocks.pressure,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const chartOne = "Chart 1 — Total realized loss by cohorts (USD)";
const perpPlaceholder =
  "Not connected — perp data source not chosen yet (Glassnode, Coinalyze or own liquidation collector)";

function Where() {
  return <output data-testid="where">{useLocation().search}</output>;
}

function show(search = "", symbol: Stream["symbol"] = "BTCUSDT") {
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
  expect(screen.queryByText(/Not connected/)).toBeNull();
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

it("shows the perp states placeholder for flow=perp and does not query seller pressure", () => {
  show("?flow=perp");
  expect(screen.getByText(perpPlaceholder)).toBeTruthy();
  expect(screen.queryByText(chartOne)).toBeNull();
  expect(screen.queryByText(/not implemented yet/)).toBeNull();
  expect(mocks.pressure).not.toHaveBeenCalled();
  expect(
    screen
      .getByRole("button", { name: "Perp states" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
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

it("renders no number in the perp view", () => {
  const { container } = show("?flow=perp");
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
  expect(screen.getByText(perpPlaceholder)).toBeTruthy();
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

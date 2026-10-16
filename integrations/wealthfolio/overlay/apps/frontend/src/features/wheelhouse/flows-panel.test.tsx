import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import { FlowsPanel } from "./flows-panel";
import type { Stream } from "./client";

afterEach(cleanup);

function Where() {
  return <output data-testid="where">{useLocation().search}</output>;
}

function show(search = "", symbol: Stream["symbol"] = "BTCUSDT") {
  return render(
    <MemoryRouter initialEntries={[`/market-intelligence${search}`]}>
      <FlowsPanel symbol={symbol} />
      <Where />
    </MemoryRouter>,
  );
}

it("shows the seller pressure placeholder by default", () => {
  show();
  expect(
    screen.getByText("Seller pressure is not implemented yet"),
  ).toBeTruthy();
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

it("shows the perp states placeholder for flow=perp", () => {
  show("?flow=perp");
  expect(
    screen.getByText("Not connected — perp data source pending"),
  ).toBeTruthy();
  expect(screen.queryByText(/not implemented yet/)).toBeNull();
  expect(
    screen
      .getByRole("button", { name: "Perp states" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});

it("falls back to seller pressure for an unknown flow value", () => {
  show("?flow=nonsense");
  expect(
    screen.getByText("Seller pressure is not implemented yet"),
  ).toBeTruthy();
});

it.each(["", "?flow=perp"])(
  "renders no number in either view (%s)",
  (search) => {
    const { container } = show(search);
    expect(container.textContent ?? "").not.toMatch(/\d/);
  },
);

it("writes the chosen view to the flow parameter and keeps other parameters", () => {
  show("?symbol=BTCUSDT&method=flows");
  fireEvent.click(screen.getByRole("button", { name: "Perp states" }));
  const params = new URLSearchParams(
    screen.getByTestId("where").textContent ?? "",
  );
  expect(params.get("flow")).toBe("perp");
  expect(params.get("method")).toBe("flows");
  expect(params.get("symbol")).toBe("BTCUSDT");
  expect(
    screen.getByText("Not connected — perp data source pending"),
  ).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Seller pressure" }));
  expect(
    new URLSearchParams(screen.getByTestId("where").textContent ?? "").get(
      "flow",
    ),
  ).toBe("seller");
  expect(
    screen.getByText("Seller pressure is not implemented yet"),
  ).toBeTruthy();
});

it.each(["ETHUSDT", "MUUSDT"] as const)(
  "says flows are BTC only for %s and shows no view switch",
  (symbol) => {
    const { container } = show("?flow=perp", symbol);
    expect(screen.getByText("Flows are BTC only")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText(/Not connected/)).toBeNull();
    expect(container.textContent ?? "").not.toMatch(/\d/);
  },
);

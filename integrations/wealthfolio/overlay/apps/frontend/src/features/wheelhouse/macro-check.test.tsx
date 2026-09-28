import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MacroCheck } from "./macro-check";
import type { MacroWatch } from "./macro-contract";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const watch: MacroWatch = {
  checked_at: "2026-09-28T10:00:00Z",
  fomc: {
    decision_at: "2026-10-28T18:00:00Z",
    meeting: "October 27-28, 2026",
    projections: false,
  },
  fomc_error: null,
  spread: {
    day: "2026-09-24",
    ten_year: 5.18,
    one_year: 4.51,
    spread: 0.67,
    inverted: false,
    history: [{ day: "2026-09-24", spread: 0.67 }],
  },
  spread_error: null,
};

function mount(body: MacroWatch) {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-28T10:00:00Z"));
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body))),
  );
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MacroCheck />
    </QueryClientProvider>,
  );
}

it("counts down to the next decision and shows the spread with its date", async () => {
  mount(watch);
  await waitFor(() => expect(screen.getByText("30 d 8 h")).toBeTruthy());
  expect(
    screen.getByText(/October 27-28, 2026 · 2026-10-28 18:00 UTC/),
  ).toBeTruthy();
  expect(screen.getByText("+0.67%")).toBeTruthy();
  expect(
    screen.getByText(/Not inverted · 10Y 5.18% · 1Y 4.51% · FRED 2026-09-24/),
  ).toBeTruthy();
});

it("reports a failed source as unavailable without a number", async () => {
  mount({ ...watch, spread: null, spread_error: "fred timed out" });
  await waitFor(() =>
    expect(screen.getByText("Unavailable: fred timed out")).toBeTruthy(),
  );
  expect(screen.queryByText("+0.67%")).toBeNull();
});

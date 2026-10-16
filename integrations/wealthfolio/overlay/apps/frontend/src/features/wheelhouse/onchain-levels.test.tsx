import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { CycleView, LevelsView } from "./onchain-contract";
import { cycleSample, levelsSample } from "./onchain-contract";
import { OnchainLevels } from "./onchain-levels";

// The shared test setup mocks matchMedia as a narrow screen; each test sets its own width.
function viewport(wide: boolean) {
  vi.mocked(window.matchMedia).mockImplementation(
    (query: string) =>
      ({
        matches: wide,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}

beforeEach(() => viewport(true));
afterEach(cleanup);

const cycleSection = () =>
  document.querySelector<HTMLDetailsElement>("#wh-onchain-cycle")!;
const sourceSection = () =>
  screen.getByText("Source").closest<HTMLDetailsElement>("details")!;

it("lists the five model lines and the three cycle components", () => {
  render(<OnchainLevels levels={levelsSample} cycle={cycleSample} />);
  for (const [name, price] of [
    ["True mean", "$98,101"],
    ["Short-term", "$106,200"],
    ["Average", "$71,500"],
    ["Long-term", "$54,301"],
    ["Median", "$63,400"],
  ]) {
    expect(screen.getByText(name).nextSibling?.textContent).toBe(price);
  }
  expect(screen.getByText("Breakout")).toBeTruthy();
  expect(screen.getByText("2026-09-23 · day 24")).toBeTruthy();
  // value, dead zone and whether the component supports the current state
  expect(screen.getByText("Depth (W vs TMM)").nextSibling?.textContent).toBe(
    "+6.46 / ±7.00 · supports",
  );
  expect(screen.getByText("Spread (STH vs TMM)").nextSibling?.textContent).toBe(
    "−3.96 / ±1.25 · supports",
  );
  expect(screen.getByText("PvS (W vs STH)").nextSibling?.textContent).toBe(
    "+10.43 / ±6.80 · supports",
  );
});

it("says when a component does not support the current state", () => {
  render(
    <OnchainLevels
      levels={levelsSample}
      cycle={{
        ...cycleSample,
        components: cycleSample.components.map((c) =>
          c.name === "spread" ? { ...c, supports: false } : c,
        ),
      }}
    />,
  );
  expect(screen.getByText("Spread (STH vs TMM)").nextSibling?.textContent).toBe(
    "−3.96 / ±1.25 · does not support",
  );
});

it("writes the source line with the version, the as-of day, the oracle note and STH", () => {
  render(<OnchainLevels levels={levelsSample} cycle={cycleSample} />);
  expect(
    screen.getByText(
      "Bitcoin Research Kit · bitview.space · BRK 0.1.0 · as of 2026-10-16 UTC",
    ),
  ).toBeTruthy();
  expect(screen.getByText("includes today (forming)")).toBeTruthy();
  expect(screen.getByText(/oracle estimates, not Bybit quotes/)).toBeTruthy();
  expect(screen.getByText(/STH \(<150d\)/)).toBeTruthy();
});

it("opens Cycle and Source on a wide screen", () => {
  render(<OnchainLevels levels={levelsSample} cycle={cycleSample} />);
  expect(cycleSection().open).toBe(true);
  expect(sourceSection().open).toBe(true);
});

it("collapses Cycle and Source on a narrow screen", () => {
  viewport(false);
  render(<OnchainLevels levels={levelsSample} cycle={cycleSample} />);
  expect(cycleSection().open).toBe(false);
  expect(sourceSection().open).toBe(false);
  expect(window.matchMedia).toHaveBeenCalledWith("(min-width: 601px)");
  // The model lines stay visible: they are the point of the tab.
  expect(screen.getByText("Average")).toBeTruthy();
});

it("makes the Cycle section a scroll target for the header badge", () => {
  render(<OnchainLevels levels={levelsSample} cycle={cycleSample} />);
  expect(cycleSection().tabIndex).toBe(-1);
});

it("shows the refreshing notice in the Source section", () => {
  render(
    <OnchainLevels
      levels={{ ...levelsSample, refreshing: true }}
      cycle={cycleSample}
    />,
  );
  expect(sourceSection().textContent).toContain("Refreshing on-chain data…");
});

it("does not show the refreshing notice when nothing is refreshing", () => {
  render(<OnchainLevels levels={levelsSample} cycle={cycleSample} />);
  expect(screen.queryByText("Refreshing on-chain data…")).toBeNull();
});

it("renders the Cycle section while both requests are still loading", () => {
  render(<OnchainLevels />);
  expect(cycleSection()).toBeTruthy();
  expect(screen.getByText("Loading cycle…")).toBeTruthy();
  expect(screen.getByText("Loading on-chain cost lines…")).toBeTruthy();
});

it("renders the Cycle section when a request failed and shows the error", () => {
  render(
    <OnchainLevels
      levelsError="Python service unavailable (HTTP 503). No simulated fallback was used."
      cycleError="Python service did not respond. Check the local workspace and retry."
    />,
  );
  expect(cycleSection()).toBeTruthy();
  expect(screen.getByText("Cycle unavailable")).toBeTruthy();
  expect(screen.getByText("On-chain cost lines unavailable")).toBeTruthy();
  expect(
    screen.getByText(
      "Python service did not respond. Check the local workspace and retry.",
    ),
  ).toBeTruthy();
  expect(screen.getByText(/HTTP 503/)).toBeTruthy();
  expect(screen.queryByText(/\$/)).toBeNull();
});

it("a request error wins over older data", () => {
  render(
    <OnchainLevels
      levels={levelsSample}
      cycle={cycleSample}
      levelsError="Python service did not respond. Check the local workspace and retry."
      cycleError="Python service did not respond. Check the local workspace and retry."
    />,
  );
  expect(screen.getByText("Cycle unavailable")).toBeTruthy();
  expect(screen.getByText("On-chain cost lines unavailable")).toBeTruthy();
  expect(screen.queryByText("Breakout")).toBeNull();
  expect(screen.queryByText("$71,500")).toBeNull();
});

it("shows unavailable data with its translated reasons and no invented numbers", () => {
  const levels: LevelsView = {
    ...levelsSample,
    data_state: "unavailable",
    reasons: ["brk_unavailable"],
    lines: [],
    as_of: null,
    brk_version: null,
    forming_at: null,
  };
  const cycle: CycleView = {
    ...cycleSample,
    data_state: "unavailable",
    reasons: ["series_missing:sth_realized_price", "brk_unavailable"],
    state: null,
    since: null,
    day: null,
    as_of: null,
    components: [],
    episodes: [],
    changes: null,
    forming_at: null,
    brk_version: null,
  };
  render(<OnchainLevels levels={levels} cycle={cycle} />);
  expect(screen.getByText("Cycle unavailable")).toBeTruthy();
  expect(screen.getByText("On-chain cost lines unavailable")).toBeTruthy();
  expect(
    screen.getAllByText(/on-chain data source unavailable/).length,
  ).toBeGreaterThan(0);
  expect(screen.getByText(/missing series sth_realized_price/)).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/\$|day \d|\b0\.00\b/);
  expect(sourceSection().textContent).toContain("BRK Unavailable");
  expect(sourceSection().textContent).toContain("as of Unavailable");
});

it("marks stale data with its as-of day and keeps the values", () => {
  render(
    <OnchainLevels
      levels={{ ...levelsSample, data_state: "stale", forming_at: null }}
      cycle={{
        ...cycleSample,
        data_state: "stale",
        forming_at: null,
        as_of: "2026-10-14",
      }}
    />,
  );
  expect(screen.getAllByText("stale · as of 2026-10-14").length).toBe(1);
  expect(screen.getByText("stale · as of 2026-10-16")).toBeTruthy();
  expect(screen.getByText("$71,500")).toBeTruthy();
  expect(screen.getByText("Breakout")).toBeTruthy();
});

it("treats reasons on a fresh reading as information, not as unavailable", () => {
  render(
    <OnchainLevels
      levels={levelsSample}
      cycle={{ ...cycleSample, reasons: ["urpd_missing"] }}
    />,
  );
  expect(screen.queryByText("Cycle unavailable")).toBeNull();
  expect(screen.getByText("Breakout")).toBeTruthy();
  expect(screen.getByText(/URPD distribution unavailable/)).toBeTruthy();
});

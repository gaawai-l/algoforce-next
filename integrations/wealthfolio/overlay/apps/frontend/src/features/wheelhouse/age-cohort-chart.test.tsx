import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AgeCohortChart } from "./age-cohort-chart";
import expected from "./age-cohorts-expected.json";
import raw from "./age-cohorts-sample.json";
import { ageCohortsSchema, type AgeCohortsView } from "./onchain-contract";

const mocks = vi.hoisted(() => ({ ageCohorts: vi.fn() }));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getAgeCohorts: mocks.ageCohorts,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const TITLE = "Chart 2 — Sell Side Breakdown by All Age Cohorts";
const sample = ageCohortsSchema.parse(raw);
// The original's reading for a sequence of choices made from its defaults.
const caseFor = (steps: unknown[]) =>
  expected.cases.find((c) => JSON.stringify(c.steps) === JSON.stringify(steps))!;

function show(view: AgeCohortsView | Error) {
  if (view instanceof Error) mocks.ageCohorts.mockRejectedValue(view);
  else mocks.ageCohorts.mockResolvedValue(view);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AgeCohortChart />
    </QueryClientProvider>,
  );
}

const panel = () => document.querySelector<HTMLElement>('[data-chart="agecohorts"]')!;
const svg = () => panel().querySelector("svg")!;
const legend = () =>
  [...panel().querySelectorAll(".wh-seller-legend button")].map(
    (button) => button.querySelector("b")!.textContent,
  );
const legendButton = (name: string) =>
  within(panel()).getByRole("button", { name: new RegExp(`^${name} `) });

it("draws the original's default view", async () => {
  show(sample);
  await screen.findByText(TITLE);
  const defaults = caseFor([["span", 720]]);
  expect(legend()).toEqual(defaults.legend);
  expect(svg().getAttribute("data-points")).toBe("720");
  expect(svg().querySelector("[data-cells]")!.getAttribute("data-cells")).toBe(
    String(defaults.cells),
  );
  // Six bands, each one path; the newest hour was still forming when the service derived it.
  expect(svg().querySelectorAll("path.wh-age-band")).toHaveLength(6);
  expect(svg().querySelector('[data-forming="true"]')).not.toBeNull();
  expect(screen.getByText(/includes the forming hour/)).toBeTruthy();
  const texts = [...svg().querySelectorAll("text")].map((label) => label.textContent);
  for (const label of [...defaults.tickText, ...defaults.priceTicks, "profit ↑", "loss ↓"])
    expect(texts).toContain(label);
});

it("keeps the legend on the newest hour while the chart reads another", async () => {
  show(sample);
  await screen.findByText(TITLE);
  const before = legend();
  fireEvent.keyDown(svg(), { key: "End" });
  const defaults = caseFor([["span", 720]]);
  expect(screen.getByRole("status").textContent).toContain(defaults.tipLast[0]);
  fireEvent.keyDown(svg(), { key: "ArrowLeft" });
  const tip = screen.getByRole("status");
  expect(tip.textContent).not.toContain(defaults.tipLast[0]);
  expect(tip.textContent).toMatch(/profit \/ loss · total \$[\d.]+[kM]? · spot \$\d{2},\d{3}/);
  expect(legend()).toEqual(before);
  fireEvent.keyDown(svg(), { key: "Escape" });
  expect(screen.queryByRole("status")).toBeNull();
});

it("reads the original's tooltip for the newest hour", async () => {
  show(sample);
  await screen.findByText(TITLE);
  fireEvent.keyDown(svg(), { key: "End" });
  const tip = screen.getByRole("status");
  const defaults = caseFor([["span", 720]]);
  const rows = [...tip.querySelectorAll(".wh-age-tip-row")].map((row) =>
    [...row.querySelectorAll("span")].map((span) => span.textContent).join(" "),
  );
  expect([tip.querySelector(".wh-age-tip-title")!.textContent, ...rows]).toEqual(
    defaults.tipLast.slice(0, -1),
  );
  expect(tip.querySelector(".wh-age-tip-foot")!.textContent).toBe(defaults.tipLast.at(-1));
});

it("follows the original through detail, scale, hidden bands and one at a time", async () => {
  show(sample);
  await screen.findByText(TITLE);
  fireEvent.click(within(panel()).getByRole("button", { name: "Relative" }));
  fireEvent.click(legendButton("5y\\+"));
  const hidden = caseFor([
    ["scale", "pct"],
    ["click", 5],
  ]);
  expect(legend()).toEqual(hidden.legend);
  expect(within(panel()).getByText(hidden.note!)).toBeTruthy();
  expect(legendButton("5y\\+").getAttribute("aria-pressed")).toBe("false");

  // Re-banding brings every band back.
  fireEvent.click(within(panel()).getByRole("button", { name: "12 bands" }));
  expect(legend()).toHaveLength(12);
  expect(within(panel()).queryByText(/visible band/)).toBeNull();

  fireEvent.click(within(panel()).getByRole("button", { name: "6 bands" }));
  fireEvent.click(within(panel()).getByRole("button", { name: "Absolute" }));
  fireEvent.click(within(panel()).getByRole("checkbox", { name: "One at a time" }));
  fireEvent.click(legendButton("6m–2y"));
  const solo = caseFor([
    ["solo", true],
    ["click", 3],
  ]);
  expect(legend()).toEqual(solo.legend);
  expect(svg().querySelectorAll("path.wh-age-band")).toHaveLength(1);
});

it("applies quick clicks in a row on top of each other", async () => {
  show(sample);
  await screen.findByText(TITLE);
  // Both clicks land before the panel renders again.
  act(() => {
    within(panel()).getByRole("button", { name: "Spent vol BTC" }).click();
    within(panel()).getByRole("button", { name: "12 bands" }).click();
  });
  // 24h and Absolute are the defaults, so this is Spent vol BTC with 12 bands.
  const both = caseFor([
    ["measure", "volb"],
    ["sma", 24],
    ["detail", "12"],
    ["scale", "abs"],
  ]);
  expect(legend()).toEqual(both.legend);
});

it("never hides the last band shown", async () => {
  show(sample);
  await screen.findByText(TITLE);
  for (const name of ["<1w", "1w–1m", "1m–6m", "6m–2y", "2y–5y", "5y\\+"])
    fireEvent.click(legendButton(name));
  expect(legend()).toEqual(["off", "off", "off", "off", "off", expect.stringMatching(/^\$/)]);
});

it("picks a band out while the legend is hovered, without redrawing the others", async () => {
  show(sample);
  await screen.findByText(TITLE);
  const paths = [...svg().querySelectorAll("path.wh-age-band")];
  fireEvent.mouseEnter(legendButton("1m–6m"));
  expect(paths.map((path) => path.getAttribute("fill-opacity"))).toEqual([
    "0.15",
    "0.15",
    "1",
    "0.15",
    "0.15",
    "0.15",
  ]);
  // The same elements, only dimmed.
  expect([...svg().querySelectorAll("path.wh-age-band")]).toEqual(paths);
  fireEvent.mouseLeave(legendButton("1m–6m"));
  expect(new Set(paths.map((path) => path.getAttribute("fill-opacity")))).toEqual(new Set(["1"]));
});

it("says the data is unavailable instead of drawing zeros", async () => {
  show({
    ...sample,
    data_state: "unavailable",
    reasons: ["series_missing:hour1:utxos_over_15y_old_realized_loss_cumulative"],
    forming_at: null,
    last_at: null,
    at: [],
    price: [],
    pnl: { profit: [], loss: [] },
    volb: { profit: [], loss: [] },
    volu: { profit: [], loss: [] },
  });
  expect(await screen.findByText("Age cohorts unavailable")).toBeTruthy();
  expect(document.querySelector("svg")).toBeNull();
});

it("keeps the controls and the legend when a choice leaves no row", async () => {
  const zero = sample.pnl.profit.map((band) => band.map(() => 0));
  show({ ...sample, pnl: { profit: zero, loss: zero } });
  expect(await screen.findByText("No data for this chart")).toBeTruthy();
  expect(document.querySelector("svg")).toBeNull();
  expect(legend()).toEqual(["—", "—", "—", "—", "—", "—"]);
  // Another measure has rows, and the controls still reach it.
  fireEvent.click(within(panel()).getByRole("button", { name: "Spent vol BTC" }));
  expect(svg().getAttribute("data-points")).toBe("720");
});

it("puts a failed request ahead of the chart", async () => {
  show(new Error("Python service unavailable (HTTP 503). No simulated fallback was used."));
  expect(await screen.findByText("Age cohorts unavailable")).toBeTruthy();
  expect(screen.getByText(/HTTP 503/)).toBeTruthy();
});

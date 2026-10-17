import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { CostBasisPanel, bandsLegend, railBands } from "./cost-basis-panel";
import { phrase } from "./i18n";
import { costBasisSample, type CostBasisView } from "./onchain-contract";

afterEach(cleanup);

const levelsTable = () =>
  screen.getByRole("table", { name: "Cost-basis levels" });
const levelCells = (name: string) =>
  within(levelsTable())
    .getAllByRole("cell")
    .filter(
      (cell) => cell.closest("tr")?.querySelector("th")?.textContent === name,
    )
    .map((cell) => cell.textContent);
const bandRows = () => [
  ...screen
    .getByRole("table", { name: "Nearest occupied bands" })
    .querySelectorAll("tbody tr"),
];
const row = (tr: Element) => ({
  side: tr.querySelector("th")!.textContent,
  range: tr.querySelector(".wh-cb-range")!.textContent,
  n: tr.querySelectorAll("td")[1].textContent,
  labels: tr.querySelector(".wh-cb-labels")?.textContent ?? "",
  change: tr.querySelectorAll("td")[2].textContent,
});
// The sample with the given bucket replaced.
const withBucket = (
  bucket: 200 | 500 | 1000,
  change: (
    b: CostBasisView["buckets"][number],
  ) => CostBasisView["buckets"][number],
): CostBasisView => ({
  ...costBasisSample,
  buckets: costBasisSample.buckets.map((b) =>
    b.bucket === bucket ? change(b) : b,
  ),
});

it("lists four resistance and four support levels for the $500 bucket", () => {
  render(<CostBasisPanel view={costBasisSample} bucket={500} />);
  expect(
    within(levelsTable())
      .getAllByRole("columnheader")
      .map((cell) => cell.textContent),
  ).toEqual(["1st", "2nd", "3rd", "4th"]);
  expect(levelCells("Resistance")).toEqual([
    "$86.0k",
    "$88.0k",
    "$96.0k",
    "$104.0k",
  ]);
  expect(levelCells("Support")).toEqual([
    "$76.0k",
    "$74.0k",
    "$70.0k",
    "$64.0k",
  ]);
});

it("lists the nearest bands far to near above spot and near to far below it", () => {
  render(<CostBasisPanel view={costBasisSample} bucket={500} />);
  const rows = bandRows();
  expect(rows).toHaveLength(9);
  expect(row(rows[0])).toEqual({
    side: "Above",
    range: "$102,000 – $104,000",
    n: "1",
    labels: "LTH M5 −σ",
    change: "+26.8%",
  });
  expect(rows.slice(0, 4).map((tr) => row(tr).range)).toEqual([
    "$102,000 – $104,000",
    "$94,000 – $96,000",
    "$86,000 – $88,000",
    "$84,000 – $86,000",
  ]);
  // The spot row is the on-chain price the percentages are measured from.
  expect(row(rows[4])).toMatchObject({
    side: "Spot",
    range: "$81,218",
    n: "",
    change: "—",
  });
  expect(rows[4].classList.contains("is-spot")).toBe(true);
  expect(row(rows[5])).toEqual({
    side: "Below",
    range: "$76,000 – $78,000",
    n: "2",
    labels: "STH M2 −σ, True mean",
    change: "−5.2%",
  });
  expect(row(rows[8])).toEqual({
    side: "Below",
    range: "$64,000 – $66,000",
    n: "2",
    labels: "STH M1 +σ, LTH M3",
    change: "−20.0%",
  });
  expect(
    screen.getByText(/M is a Gaussian component of that cohort/),
  ).toBeTruthy();
});

it("says under O1 that spot is the close of the snapshot's day", () => {
  render(
    <CostBasisPanel
      view={{
        ...costBasisSample,
        rules: ["O1"],
        forming_at: null,
        urpd_date: "2026-10-15",
        lines_as_of: "2026-10-15",
      }}
      bucket={500}
    />,
  );
  const spot = bandRows().find((tr) => tr.classList.contains("is-spot"))!;
  expect(row(spot)).toMatchObject({
    side: "Spot",
    range: "$81,218",
    labels: "on-chain price · 2026-10-15 close",
  });
  expect(phrase("zh", "costBasis.spotClose", { date: "2026-10-15" })).toBe(
    "链上价格 · 2026-10-15 收盘价",
  );
});

it("keeps the spot note without O1", () => {
  render(
    <CostBasisPanel
      view={{ ...costBasisSample, rules: ["O5"] }}
      bucket={500}
    />,
  );
  const spot = bandRows().find((tr) => tr.classList.contains("is-spot"))!;
  expect(row(spot).labels).toBe("on-chain price");
});

it("reads the selected bucket", () => {
  render(<CostBasisPanel view={costBasisSample} bucket={1000} />);
  expect(levelCells("Resistance")[1]).toBe("$90.0k");
});

it("fills a missing level with a dash", () => {
  render(
    <CostBasisPanel
      view={withBucket(500, (b) => ({
        ...b,
        above: b.above.slice(0, 3),
        resistance: b.resistance.slice(0, 3),
      }))}
      bucket={500}
    />,
  );
  expect(levelCells("Resistance")).toEqual(["$86.0k", "$88.0k", "$96.0k", "—"]);
  expect(bandRows()).toHaveLength(8);
});

it("says when the selected bucket is not available and why", () => {
  render(
    <CostBasisPanel
      view={{
        ...costBasisSample,
        reasons: ["urpd_missing:sth:lin200"],
        buckets: costBasisSample.buckets.filter((b) => b.bucket !== 200),
      }}
      bucket={200}
    />,
  );
  expect(screen.getByText("Not available for this bucket size")).toBeTruthy();
  expect(
    screen.getByText("STH URPD snapshot missing for the $200 bucket"),
  ).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
});

it("explains a missing bucket only with its own and the shared reasons", () => {
  render(
    <CostBasisPanel
      view={{
        ...costBasisSample,
        reasons: [
          "brk_unavailable",
          "urpd_grid_partial:lin500",
          "urpd_missing:sth:lin200",
        ],
        buckets: costBasisSample.buckets.filter((b) => b.bucket !== 200),
      }}
      bucket={200}
    />,
  );
  expect(
    screen.getByText(/STH URPD snapshot missing for the \$200 bucket/)
      .textContent,
  ).toBe(
    "on-chain data source unavailable · STH URPD snapshot missing for the $200 bucket",
  );
  expect(screen.queryByText(/\$500 bucket/)).toBeNull();
});

it("notes a snapshot that was still forming and a refresh in progress", () => {
  render(
    <CostBasisPanel
      view={{ ...costBasisSample, refreshing: true }}
      bucket={500}
    />,
  );
  expect(
    screen.getByText("the 2026-10-16 snapshot was still forming"),
  ).toBeTruthy();
  expect(screen.getByRole("status").textContent).toBe(
    "Refreshing cost-basis levels…",
  );
});

it("has no forming note or refresh notice when neither applies", () => {
  render(
    <CostBasisPanel
      view={{ ...costBasisSample, forming_at: null }}
      bucket={500}
    />,
  );
  expect(screen.queryByText(/still forming/)).toBeNull();
  expect(screen.queryByRole("status")).toBeNull();
});

it("shows loading before the first reading", () => {
  render(<CostBasisPanel bucket={500} />);
  expect(screen.getByText("Loading cost-basis levels…")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
});

it("a request error wins over older data", () => {
  render(
    <CostBasisPanel view={costBasisSample} error="HTTP 503" bucket={500} />,
  );
  expect(screen.getByText("Cost-basis levels unavailable")).toBeTruthy();
  expect(screen.getByText("HTTP 503")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(document.body.textContent).not.toMatch(/\$/);
});

it("shows unavailable data with its reasons and no numbers", () => {
  render(
    <CostBasisPanel
      view={{
        ...costBasisSample,
        data_state: "unavailable",
        reasons: ["brk_unavailable"],
        buckets: [],
        forming_at: null,
      }}
      bucket={500}
    />,
  );
  expect(screen.getByText("Cost-basis levels unavailable")).toBeTruthy();
  expect(screen.getByText("on-chain data source unavailable")).toBeTruthy();
  expect(document.body.textContent).not.toMatch(/\$/);
});

it("notes a refresh in progress while the reading is unavailable", () => {
  render(
    <CostBasisPanel
      view={{
        ...costBasisSample,
        data_state: "unavailable",
        reasons: ["brk_unavailable"],
        buckets: [],
        forming_at: null,
        refreshing: true,
      }}
      bucket={500}
    />,
  );
  expect(screen.getByRole("status").textContent).toBe(
    "Refreshing cost-basis levels…",
  );
});

it("dates stale data by the older of its URPD and cost-line days", () => {
  render(
    <CostBasisPanel
      view={{
        ...costBasisSample,
        data_state: "stale",
        lines_as_of: "2026-10-15",
      }}
      bucket={500}
    />,
  );
  expect(screen.getByText("stale · as of 2026-10-15")).toBeTruthy();
  cleanup();
  render(
    <CostBasisPanel
      view={{
        ...costBasisSample,
        data_state: "stale",
        urpd_date: "2026-10-14",
      }}
      bucket={500}
    />,
  );
  expect(screen.getByText("stale · as of 2026-10-14")).toBeTruthy();
});

it("marks stale data with its URPD day and keeps the values", () => {
  render(
    <CostBasisPanel
      view={{ ...costBasisSample, data_state: "stale" }}
      bucket={500}
    />,
  );
  expect(screen.getByText("stale · as of 2026-10-16")).toBeTruthy();
  expect(levelCells("Resistance")[0]).toBe("$86.0k");
});

it("maps the selected bucket's peaks to rail bands and filters by cohort", () => {
  const b500 = costBasisSample.buckets[1];
  const all = railBands(b500, { sth: true, lth: true });
  expect(all.map((b) => b.id)).toEqual([
    "sth-1",
    "sth-2",
    "lth-1",
    "lth-2",
    "lth-3",
    "lth-4",
    "lth-5",
  ]);
  const sth2 = b500.sth.peaks[1];
  expect(all[1]).toEqual({
    id: "sth-2",
    cohort: "sth",
    index: 2,
    price: sth2.price,
    low: sth2.price - sth2.width / 2,
    high: sth2.price + sth2.width / 2,
    strength: sth2.strength,
    btc: sth2.btc,
    share: sth2.share,
  });
  expect(
    railBands(b500, { sth: false, lth: true }).every((b) => b.cohort === "lth"),
  ).toBe(true);
  expect(railBands(b500, { sth: false, lth: false })).toEqual([]);
  expect(railBands(undefined, { sth: true, lth: true })).toEqual([]);
});

it("writes the band legend with the total, the floor and the share in profit", () => {
  const en = (
    key: Parameters<typeof phrase>[1],
    vars?: Record<string, string | number>,
  ) => phrase("en", key, vars);
  const b500 = costBasisSample.buckets[1];
  expect(bandsLegend(en, b500, "sth", false)).toBe(
    "3.66M BTC ≥$1k · 62% in profit",
  );
  expect(bandsLegend(en, b500, "lth", true)).toBe(
    "12.8M BTC ≥$1k · 59% in profit (stale)",
  );
  // The floor is the service's fixed $1k, wherever the bucket's domain starts.
  expect(bandsLegend(en, { ...b500, domain_low: 3000 }, "sth", false)).toBe(
    "3.66M BTC ≥$1k · 62% in profit",
  );
  expect(
    bandsLegend(
      en,
      { ...b500, sth: { ...b500.sth, in_profit: null } },
      "sth",
      false,
    ),
  ).toBe("3.66M BTC ≥$1k · — in profit");
});

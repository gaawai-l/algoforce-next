import { z } from "zod";
import type { components } from "./api-schema";

export type CycleView = components["schemas"]["CycleView"];
export type LevelsView = components["schemas"]["LevelsView"];
export type SellerPressureView = components["schemas"]["SellerPressureView"];
export type CostBasisView = components["schemas"]["CostBasisView"];
export type SellSideView = components["schemas"]["SellSideView"];
export type AgeCohortsView = components["schemas"]["AgeCohortsView"];
export type BucketCostBasis = components["schemas"]["BucketCostBasis"];
export type CostFlowView = components["schemas"]["CostFlowView"];
export type FlowGrid = components["schemas"]["FlowGrid"];
export type FlowWindow = components["schemas"]["FlowWindow"];
export type CohortColumns = components["schemas"]["CohortColumns"];
export type AgeFlow = components["schemas"]["AgeFlow"];

const time = z.string().datetime({ offset: true });
const day = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const dataState = z.enum(["fresh", "stale", "unavailable"]);
// The rules a view's payload was derived under; empty means the original v1 rules.
const rules = z.array(z.enum(["O1", "O2", "O3", "O4", "O5", "O6"]));
const cycleState = z.enum([
  "advance",
  "breakout",
  "pressure",
  "repair",
  "breakdown",
  "capitulation",
]);

export const cycleViewSchema: z.ZodType<CycleView, z.ZodTypeDef, unknown> =
  z.object({
    data_state: dataState,
    reasons: z.array(z.string()),
    refreshing: z.boolean(),
    forming_at: time.nullable(),
    as_of: day.nullable(),
    state: cycleState.nullable(),
    since: day.nullable(),
    day: z.number().int().nullable(),
    components: z.array(
      z.object({
        name: z.enum(["depth", "pvs", "spread"]),
        value: z.number(),
        deadband: z.number(),
        supports: z.boolean(),
      }),
    ),
    episodes: z.array(
      z.object({
        state: cycleState,
        start: day,
        end: day,
        days: z.number().int(),
      }),
    ),
    changes: z.number().int().nullable(),
    brk_version: z.string().nullable(),
    rules,
    rules_pending: z.boolean(),
  });

// O5 adds the 1d–1w cost line.
const lineName = z.enum([
  "true_mean",
  "short_term",
  "average",
  "long_term",
  "median",
  "one_day_to_week",
]);
const pressureDataState = z.enum(["fresh", "delayed", "stale", "unavailable"]);
const pressureLevels = z.object({
  p95: z.number().nullable(),
  p75: z.number().nullable(),
  n: z.number().int(),
});
// O3 marks an hour without a block (flows 0, levels carried over) and a value a series gap left
// unknown, which is null and never 0. Under v1 no value is null and both marks are false.
const pressureMarks = { no_block: z.boolean(), gap: z.boolean() };
// O2 gives each point its hour's own thresholds and a level against them. Null under v1 and on
// the price; a level is also null while its thresholds or value are, or its hour is forming (O1).
const pressureRolling = {
  p95: z.number().nullable(),
  p75: z.number().nullable(),
  level: z.enum(["extreme", "warning", "none"]).nullable(),
};
const pressurePoint = z.object({
  at: time,
  value: z.number().nullable(),
  ...pressureMarks,
  ...pressureRolling,
});

export const levelsViewSchema: z.ZodType<LevelsView, z.ZodTypeDef, unknown> =
  z.object({
    data_state: dataState,
    reasons: z.array(z.string()),
    refreshing: z.boolean(),
    forming_at: time.nullable(),
    as_of: time.nullable(),
    urpd_date: day.nullable(),
    onchain_close: z.number().nullable(),
    lines: z.array(
      z.object({
        name: lineName,
        price: z.number(),
      }),
    ),
    brk_version: z.string().nullable(),
    rules,
    rules_pending: z.boolean(),
  });

const cohort = z.enum(["sth", "lth"]);
const cohortClusters = z.object({
  cohort,
  total: z.number(),
  in_profit: z.number().nullable(),
  peaks: z.array(
    z.object({
      price: z.number(),
      width: z.number(),
      btc: z.number(),
      share: z.number(),
      strength: z.number(),
    }),
  ),
  components: z.array(
    z.object({
      mu: z.number(),
      sigma: z.number(),
      share: z.number(),
      btc: z.number(),
    }),
  ),
});
const costBasisCandidate = z.object({
  kind: z.enum(["line", "component"]),
  price: z.number(),
  line: lineName.nullable(),
  cohort: cohort.nullable(),
  index: z.number().int().nullable(),
  edge: z.enum(["low", "mid", "high"]).nullable(),
});
const costBasisBand = z.object({
  low: z.number(),
  high: z.number(),
  candidates: z.array(costBasisCandidate),
});

export const costBasisViewSchema: z.ZodType<
  CostBasisView,
  z.ZodTypeDef,
  unknown
> = z.object({
  data_state: dataState,
  reasons: z.array(z.string()),
  refreshing: z.boolean(),
  forming_at: time.nullable(),
  urpd_date: day.nullable(),
  lines_as_of: day.nullable(),
  snapshot_at: time.nullable(),
  computed_at: time.nullable(),
  buckets: z.array(
    z.object({
      bucket: z.union([z.literal(200), z.literal(500), z.literal(1000)]),
      domain_low: z.number(),
      domain_high: z.number(),
      spot: z.number(),
      sth: cohortClusters,
      lth: cohortClusters,
      above: z.array(costBasisBand),
      below: z.array(costBasisBand),
      resistance: z.array(z.number()),
      support: z.array(z.number()),
    }),
  ),
  brk_version: z.string().nullable(),
  rules,
  rules_pending: z.boolean(),
});

export const sellerPressureSchema: z.ZodType<
  SellerPressureView,
  z.ZodTypeDef,
  unknown
> = z.object({
  data_state: pressureDataState,
  reasons: z.array(z.string()),
  refreshing: z.boolean(),
  forming_at: time.nullable(),
  last_at: time.nullable(),
  loss: z.array(
    z.object({
      at: time,
      lth: z.number().nullable(),
      sth: z.number().nullable(),
      ...pressureMarks,
      ...pressureRolling,
    }),
  ),
  share: z.array(pressurePoint),
  supply: z.array(pressurePoint),
  price: z.array(pressurePoint),
  loss_levels: pressureLevels.nullable(),
  share_levels: pressureLevels.nullable(),
  supply_levels: pressureLevels.nullable(),
  xgap: z.number().int().nullable(),
  qc: z.array(z.enum(["hour_gap", "intraday_legs", "sth_supply"])),
  brk_version: z.string().nullable(),
  rules,
  rules_pending: z.boolean(),
  // O1's current reading, the newest closed row; null under v1 and when none has closed.
  closed_at: time.nullable(),
  // O2's hours in a row at warning or above, back from the current reading; never a stand-in 0.
  loss_run: z.number().int().nullable(),
  share_run: z.number().int().nullable(),
  supply_run: z.number().int().nullable(),
});

const sellSideLegs = z.object({
  lth_profit: z.array(z.number()),
  lth_loss: z.array(z.number()),
  sth_profit: z.array(z.number()),
  sth_loss: z.array(z.number()),
  sth_profit_x1: z.array(z.number()),
  sth_loss_x1: z.array(z.number()),
  sth_profit_x24: z.array(z.number()),
  sth_loss_x24: z.array(z.number()),
});

// Columns, one entry per kept hour; a column of another length would misplace every value after
// its gap, so the payload is refused rather than drawn.
export const sellSideSchema: z.ZodType<SellSideView, z.ZodTypeDef, unknown> = z
  .object({
    data_state: pressureDataState,
    reasons: z.array(z.string()),
    refreshing: z.boolean(),
    forming_at: time.nullable(),
    last_at: time.nullable(),
    at: z.array(time),
    price: z.array(z.number()),
    pnl: sellSideLegs,
    volb: sellSideLegs,
    volu: sellSideLegs,
    xgap: z.number().int().nullable(),
    qc: z.array(z.literal("intraday_legs")),
    brk_version: z.string().nullable(),
    rules,
    rules_pending: z.boolean(),
  })
  .refine(
    (view) =>
      view.price.length === view.at.length &&
      [view.pnl, view.volb, view.volu].every((legs) =>
        Object.values(legs).every((column) => column.length === view.at.length),
      ),
    { message: "sell-side columns differ in length" },
  );

const ageBands = z.object({
  profit: z.array(z.array(z.number())),
  loss: z.array(z.array(z.number())),
});

// Twelve bands a side, each a column lined up with `at`; an unavailable payload has no bands.
export const ageCohortsSchema: z.ZodType<AgeCohortsView, z.ZodTypeDef, unknown> = z
  .object({
    data_state: pressureDataState,
    reasons: z.array(z.string()),
    refreshing: z.boolean(),
    forming_at: time.nullable(),
    last_at: time.nullable(),
    at: z.array(time),
    price: z.array(z.number()),
    pnl: ageBands,
    volb: ageBands,
    volu: ageBands,
    brk_version: z.string().nullable(),
    rules,
    rules_pending: z.boolean(),
  })
  .refine(
    (view) =>
      view.price.length === view.at.length &&
      [view.pnl, view.volb, view.volu].every((bands) =>
        [bands.profit, bands.loss].every(
          (side) =>
            side.length === (view.at.length ? 12 : 0) &&
            side.every((column) => column.length === view.at.length),
        ),
      ),
    { message: "age-cohort columns differ in length" },
  );

const cohortColumns = z.object({
  all: z.array(z.number()),
  sth: z.array(z.number()),
  lth: z.array(z.number()),
});
const fitsFloors = (columns: CohortColumns, floors: number) =>
  columns.all.length === floors &&
  columns.sth.length === floors &&
  columns.lth.length === floors;

// The inputs of Charts 3 and 4: every column, D's and each window's, and each age group and the
// age floor, has one entry per floor of its grid; a column of another length would misplace every
// value after its gap, so the payload is refused rather than drawn. The ages are on the $500 grid.
export const costFlowSchema: z.ZodType<CostFlowView, z.ZodTypeDef, unknown> = z
  .object({
    data_state: dataState,
    reasons: z.array(z.string()),
    refreshing: z.boolean(),
    forming_at: time.nullable(),
    now_day: day.nullable(),
    snapshot_at: time.nullable(),
    computed_at: time.nullable(),
    spot: z.number().nullable(),
    grids: z.array(
      z.object({
        step: z.union([z.literal(200), z.literal(500)]),
        floors: z.array(z.number()),
        now: cohortColumns,
        windows: z.array(
          z.object({
            window: z.enum(["1d", "7d", "30d", "90d"]),
            then_day: day,
            then: cohortColumns,
          }),
        ),
      }),
    ),
    age: z
      .object({
        groups: z.array(z.array(z.number())),
        band: z.array(z.number().int()),
      })
      .nullable(),
    qc: z.array(z.string()),
    brk_version: z.string().nullable(),
    rules,
    rules_pending: z.boolean(),
  })
  .refine(
    (view) =>
      view.grids.every(
        (grid) =>
          fitsFloors(grid.now, grid.floors.length) &&
          grid.windows.every((found) => fitsFloors(found.then, grid.floors.length)),
      ),
    { message: "cost-flow columns differ from their floors in length" },
  )
  .refine(
    (view) => {
      if (!view.age) return true;
      // Without a $500 grid `floors` is undefined, which no length matches.
      const floors = view.grids.find((grid) => grid.step === 500)?.floors.length;
      return (
        view.age.band.length === floors &&
        view.age.groups.every((group) => group.length === floors)
      );
    },
    { message: "cost-flow ages do not match the $500 grid" },
  );

// Hand-written payloads shared by contract and view tests. The cycle components and the
// breakout episode follow the 2026-10-16 fixture result: depth = 100*ln(W/TMM), spread =
// 100*ln(STH/TMM), pvs = depth - spread, and supports = sign matches the state's expected sign
// (breakout expects depth +, pvs +, spread -). The sample lists 2 episodes while `changes` is 48;
// the real service has changes = len(episodes) - 1 with the full history.
export const cycleSample: CycleView = {
  data_state: "fresh",
  reasons: [],
  refreshing: false,
  forming_at: "2026-10-16T00:00:00+00:00",
  as_of: "2026-10-16",
  state: "breakout",
  since: "2026-09-23",
  day: 24,
  components: [
    { name: "depth", value: 6.46, deadband: 7.0, supports: true },
    { name: "pvs", value: 10.43, deadband: 6.8, supports: true },
    { name: "spread", value: -3.96, deadband: 1.25, supports: true },
  ],
  episodes: [
    { state: "repair", start: "2026-08-25", end: "2026-09-22", days: 29 },
    { state: "breakout", start: "2026-09-23", end: "2026-10-16", days: 24 },
  ],
  changes: 48,
  brk_version: "0.1.0",
  rules: [],
  rules_pending: false,
};

// The line prices are illustrative, not a fixture result.
export const levelsSample: LevelsView = {
  data_state: "fresh",
  reasons: [],
  refreshing: false,
  forming_at: "2026-10-16T00:00:00+00:00",
  as_of: "2026-10-16T00:00:00+00:00",
  urpd_date: "2026-10-16",
  onchain_close: 112345.67,
  lines: [
    { name: "true_mean", price: 98100.5 },
    { name: "short_term", price: 106200.25 },
    { name: "average", price: 71500.0 },
    { name: "long_term", price: 54300.75 },
    { name: "median", price: 63400.1 },
  ],
  brk_version: "0.1.0",
  rules: [],
  rules_pending: false,
};

// The BucketCostBasis results of `cost_basis()` on the 2026-10-16 18:29Z golden fixtures
// (services/analytics/tests/onchain/fixtures/brk-2026-10-16T1829Z), one per bucket width, dumped
// once by a throwaway script. Peak and candidate prices, band bounds, resistance/support, the
// component mu and sigma, spot and the domain are the exact backend values; every other float is
// rounded to 6 significant digits. The envelope timestamps are illustrative.
const bucket200: BucketCostBasis = {
  bucket: 200,
  domain_low: 1000,
  domain_high: 125800,
  spot: 81217.6,
  sth: {
    cohort: "sth",
    total: 3664210,
    in_profit: 0.63853,
    peaks: [
      {
        price: 63500,
        width: 6900.92,
        btc: 1261490,
        share: 0.344273,
        strength: 0.703599,
      },
      {
        price: 82300,
        width: 9929.34,
        btc: 1924160,
        share: 0.525124,
        strength: 1,
      },
    ],
    components: [
      {
        mu: 63389.45800127132,
        sigma: 1657.338842360347,
        share: 0.366985,
        btc: 1344710,
      },
      {
        mu: 80898.68892900509,
        sigma: 3639.2834552904933,
        share: 0.633015,
        btc: 2319500,
      },
    ],
  },
  lth: {
    cohort: "lth",
    total: 12782600,
    in_profit: 0.586477,
    peaks: [
      {
        price: 6900,
        width: 20566.8,
        btc: 2390630,
        share: 0.187022,
        strength: 0.449205,
      },
      {
        price: 39100,
        width: 12983.6,
        btc: 884964,
        share: 0.069232,
        strength: 0.179763,
      },
      {
        price: 67300,
        width: 60264.3,
        btc: 6363510,
        share: 0.497827,
        strength: 0.369224,
      },
      {
        price: 84900,
        width: 18303,
        btc: 2629850,
        share: 0.205737,
        strength: 0.779248,
      },
      {
        price: 108100,
        width: 61237,
        btc: 5590090,
        share: 0.437321,
        strength: 0.248893,
      },
    ],
    components: [
      {
        mu: 6579.687610476609,
        sigma: 3208.5627441526117,
        share: 0.122647,
        btc: 1567740,
      },
      {
        mu: 29708.363841708426,
        sigma: 14117.65900749825,
        share: 0.263234,
        btc: 3364810,
      },
      {
        mu: 65838.77735055189,
        sigma: 5461.468896579261,
        share: 0.16458,
        btc: 2103750,
      },
      {
        mu: 87773.7801090172,
        sigma: 6726.668286223365,
        share: 0.253901,
        btc: 3245510,
      },
      {
        mu: 110049.42811743022,
        sigma: 6415.044186905245,
        share: 0.195638,
        btc: 2500760,
      },
    ],
  },
  above: [
    {
      low: 84000,
      high: 86000,
      candidates: [
        {
          kind: "component",
          price: 84537.97238429559,
          line: null,
          cohort: "sth",
          index: 2,
          edge: "high",
        },
      ],
    },
    {
      low: 86000,
      high: 88000,
      candidates: [
        {
          kind: "component",
          price: 87773.7801090172,
          line: null,
          cohort: "lth",
          index: 4,
          edge: "mid",
        },
      ],
    },
    {
      low: 94000,
      high: 96000,
      candidates: [
        {
          kind: "component",
          price: 94500.44839524056,
          line: null,
          cohort: "lth",
          index: 4,
          edge: "high",
        },
      ],
    },
    {
      low: 102000,
      high: 104000,
      candidates: [
        {
          kind: "component",
          price: 103634.38393052497,
          line: null,
          cohort: "lth",
          index: 5,
          edge: "low",
        },
      ],
    },
  ],
  below: [
    {
      low: 76000,
      high: 78000,
      candidates: [
        {
          kind: "component",
          price: 77259.40547371459,
          line: null,
          cohort: "sth",
          index: 2,
          edge: "low",
        },
        {
          kind: "line",
          price: 77482,
          line: "true_mean",
          cohort: null,
          index: null,
          edge: null,
        },
      ],
    },
    {
      low: 74000,
      high: 76000,
      candidates: [
        {
          kind: "line",
          price: 74475,
          line: "short_term",
          cohort: null,
          index: null,
          edge: null,
        },
      ],
    },
    {
      low: 70000,
      high: 72000,
      candidates: [
        {
          kind: "component",
          price: 71300.24624713114,
          line: null,
          cohort: "lth",
          index: 3,
          edge: "high",
        },
      ],
    },
    {
      low: 64000,
      high: 66000,
      candidates: [
        {
          kind: "component",
          price: 65046.796843631666,
          line: null,
          cohort: "sth",
          index: 1,
          edge: "high",
        },
        {
          kind: "component",
          price: 65838.77735055189,
          line: null,
          cohort: "lth",
          index: 3,
          edge: "mid",
        },
      ],
    },
  ],
  resistance: [86000, 88000, 96000, 104000],
  support: [76000, 74000, 70000, 64000],
};
const bucket500: BucketCostBasis = {
  bucket: 500,
  domain_low: 1000,
  domain_high: 126000,
  spot: 81217.6,
  sth: {
    cohort: "sth",
    total: 3664210,
    in_profit: 0.622719,
    peaks: [
      {
        price: 63750,
        width: 6954.59,
        btc: 1213350,
        share: 0.331136,
        strength: 0.701002,
      },
      {
        price: 82250,
        width: 9971.09,
        btc: 1910410,
        share: 0.521371,
        strength: 1,
      },
    ],
    components: [
      {
        mu: 63384.48319993328,
        sigma: 1669.984853581456,
        share: 0.367179,
        btc: 1345420,
      },
      {
        mu: 80916.34430526111,
        sigma: 3654.5485623887253,
        share: 0.632821,
        btc: 2318790,
      },
    ],
  },
  lth: {
    cohort: "lth",
    total: 12782600,
    in_profit: 0.58545,
    peaks: [
      {
        price: 6750,
        width: 15064.9,
        btc: 1996470,
        share: 0.156187,
        strength: 0.434233,
      },
      {
        price: 38750,
        width: 82611.7,
        btc: 7429860,
        share: 0.581249,
        strength: 0.176633,
      },
      {
        price: 67250,
        width: 60252.3,
        btc: 6383130,
        share: 0.499362,
        strength: 0.374946,
      },
      {
        price: 84750,
        width: 18514.5,
        btc: 2638160,
        share: 0.206387,
        strength: 0.777673,
      },
      {
        price: 108250,
        width: 61327.7,
        btc: 5587220,
        share: 0.437096,
        strength: 0.244641,
      },
    ],
    components: [
      {
        mu: 6586.996725958441,
        sigma: 3189.002665847017,
        share: 0.122569,
        btc: 1566740,
      },
      {
        mu: 29702.17743804441,
        sigma: 14099.605173985166,
        share: 0.263271,
        btc: 3365280,
      },
      {
        mu: 65850.37214844045,
        sigma: 5470.319982441565,
        share: 0.164848,
        btc: 2107180,
      },
      {
        mu: 87787.53329966724,
        sigma: 6717.24182179979,
        share: 0.25351,
        btc: 3240510,
      },
      {
        mu: 110026.39828688871,
        sigma: 6445.859612573211,
        share: 0.195803,
        btc: 2502860,
      },
    ],
  },
  above: [
    {
      low: 84000,
      high: 86000,
      candidates: [
        {
          kind: "component",
          price: 84570.89286764983,
          line: null,
          cohort: "sth",
          index: 2,
          edge: "high",
        },
      ],
    },
    {
      low: 86000,
      high: 88000,
      candidates: [
        {
          kind: "component",
          price: 87787.53329966724,
          line: null,
          cohort: "lth",
          index: 4,
          edge: "mid",
        },
      ],
    },
    {
      low: 94000,
      high: 96000,
      candidates: [
        {
          kind: "component",
          price: 94504.77512146703,
          line: null,
          cohort: "lth",
          index: 4,
          edge: "high",
        },
      ],
    },
    {
      low: 102000,
      high: 104000,
      candidates: [
        {
          kind: "component",
          price: 103580.5386743155,
          line: null,
          cohort: "lth",
          index: 5,
          edge: "low",
        },
      ],
    },
  ],
  below: [
    {
      low: 76000,
      high: 78000,
      candidates: [
        {
          kind: "component",
          price: 77261.79574287239,
          line: null,
          cohort: "sth",
          index: 2,
          edge: "low",
        },
        {
          kind: "line",
          price: 77482,
          line: "true_mean",
          cohort: null,
          index: null,
          edge: null,
        },
      ],
    },
    {
      low: 74000,
      high: 76000,
      candidates: [
        {
          kind: "line",
          price: 74475,
          line: "short_term",
          cohort: null,
          index: null,
          edge: null,
        },
      ],
    },
    {
      low: 70000,
      high: 72000,
      candidates: [
        {
          kind: "component",
          price: 71320.69213088202,
          line: null,
          cohort: "lth",
          index: 3,
          edge: "high",
        },
      ],
    },
    {
      low: 64000,
      high: 66000,
      candidates: [
        {
          kind: "component",
          price: 65054.468053514734,
          line: null,
          cohort: "sth",
          index: 1,
          edge: "high",
        },
        {
          kind: "component",
          price: 65850.37214844045,
          line: null,
          cohort: "lth",
          index: 3,
          edge: "mid",
        },
      ],
    },
  ],
  resistance: [86000, 88000, 96000, 104000],
  support: [76000, 74000, 70000, 64000],
};
const bucket1000: BucketCostBasis = {
  bucket: 1000,
  domain_low: 1000,
  domain_high: 126000,
  spot: 81217.6,
  sth: {
    cohort: "sth",
    total: 3664210,
    in_profit: 0.622719,
    peaks: [
      {
        price: 63500,
        width: 6967.3,
        btc: 1261490,
        share: 0.344273,
        strength: 0.711388,
      },
      {
        price: 82500,
        width: 10178.4,
        btc: 1974440,
        share: 0.538844,
        strength: 1,
      },
    ],
    components: [
      {
        mu: 63340.36791894213,
        sigma: 1649.5799477519638,
        share: 0.365901,
        btc: 1340740,
      },
      {
        mu: 80968.75683638708,
        sigma: 3772.963352955625,
        share: 0.634099,
        btc: 2323470,
      },
    ],
  },
  lth: {
    cohort: "lth",
    total: 12782600,
    in_profit: 0.58545,
    peaks: [
      {
        price: 7500,
        width: 14400.3,
        btc: 2006260,
        share: 0.156952,
        strength: 0.38238,
      },
      {
        price: 39500,
        width: 81824.7,
        btc: 7429860,
        share: 0.581249,
        strength: 0.179823,
      },
      {
        price: 67500,
        width: 60242.1,
        btc: 6477680,
        share: 0.506759,
        strength: 0.372921,
      },
      {
        price: 85500,
        width: 18245.9,
        btc: 2693690,
        share: 0.210731,
        strength: 0.775369,
      },
      {
        price: 108500,
        width: 61360,
        btc: 5512420,
        share: 0.431245,
        strength: 0.252165,
      },
    ],
    components: [
      {
        mu: 6670.232548726404,
        sigma: 3304.4323641067567,
        share: 0.124637,
        btc: 1593180,
      },
      {
        mu: 29798.489472690715,
        sigma: 14081.723604797178,
        share: 0.260775,
        btc: 3333380,
      },
      {
        mu: 65928.25695987564,
        sigma: 5566.295141772139,
        share: 0.167176,
        btc: 2136950,
      },
      {
        mu: 88082.39567977808,
        sigma: 6702.73977251619,
        share: 0.254013,
        btc: 3246940,
      },
      {
        mu: 110125.16309942618,
        sigma: 6361.0521359906825,
        share: 0.193398,
        btc: 2472130,
      },
    ],
  },
  above: [
    {
      low: 84000,
      high: 86000,
      candidates: [
        {
          kind: "component",
          price: 84741.72018934271,
          line: null,
          cohort: "sth",
          index: 2,
          edge: "high",
        },
      ],
    },
    {
      low: 88000,
      high: 90000,
      candidates: [
        {
          kind: "component",
          price: 88082.39567977808,
          line: null,
          cohort: "lth",
          index: 4,
          edge: "mid",
        },
      ],
    },
    {
      low: 94000,
      high: 96000,
      candidates: [
        {
          kind: "component",
          price: 94785.13545229427,
          line: null,
          cohort: "lth",
          index: 4,
          edge: "high",
        },
      ],
    },
    {
      low: 102000,
      high: 104000,
      candidates: [
        {
          kind: "component",
          price: 103764.1109634355,
          line: null,
          cohort: "lth",
          index: 5,
          edge: "low",
        },
      ],
    },
  ],
  below: [
    {
      low: 76000,
      high: 78000,
      candidates: [
        {
          kind: "component",
          price: 77195.79348343145,
          line: null,
          cohort: "sth",
          index: 2,
          edge: "low",
        },
        {
          kind: "line",
          price: 77482,
          line: "true_mean",
          cohort: null,
          index: null,
          edge: null,
        },
      ],
    },
    {
      low: 74000,
      high: 76000,
      candidates: [
        {
          kind: "line",
          price: 74475,
          line: "short_term",
          cohort: null,
          index: null,
          edge: null,
        },
      ],
    },
    {
      low: 70000,
      high: 72000,
      candidates: [
        {
          kind: "component",
          price: 71494.55210164777,
          line: null,
          cohort: "lth",
          index: 3,
          edge: "high",
        },
      ],
    },
    {
      low: 64000,
      high: 66000,
      candidates: [
        {
          kind: "component",
          price: 64989.94786669409,
          line: null,
          cohort: "sth",
          index: 1,
          edge: "high",
        },
        {
          kind: "component",
          price: 65928.25695987564,
          line: null,
          cohort: "lth",
          index: 3,
          edge: "mid",
        },
      ],
    },
  ],
  resistance: [86000, 90000, 96000, 104000],
  support: [76000, 74000, 70000, 64000],
};

// To regenerate the buckets, dump `golden_result()` in services/analytics/tests/onchain/test_onchain_costbasis.py.
export const costBasisSample: CostBasisView = {
  data_state: "fresh",
  reasons: [],
  refreshing: false,
  forming_at: "2026-10-16T00:00:00Z",
  urpd_date: "2026-10-16",
  lines_as_of: "2026-10-16",
  snapshot_at: "2026-10-16T18:29:40Z",
  computed_at: "2026-10-16T18:30:12Z",
  buckets: [bucket200, bucket500, bucket1000],
  brk_version: "0.12.2",
  rules: [],
  rules_pending: false,
};

const PRESSURE_POINTS = 2200;
const HOUR_MS = 3_600_000;
const PRESSURE_LAST_AT = Date.parse("2026-10-16T08:00:00Z");
// What every v1 point carries: no O3 marks and no O2 thresholds.
const V1_POINT = {
  no_block: false,
  gap: false,
  p95: null,
  p75: null,
  level: null,
} as const;

// Synthetic hourly series for tests and previews, not a service result. Every value is positive
// and smooth; only the last point and the three level triples carry the 2026-10-16 fixture
// parity values (the loss/share/supply results of the original v1 rules). A factory, so callers
// that slice or mutate the arrays never share state.
export function pressureSample(): SellerPressureView {
  const loss: SellerPressureView["loss"] = [];
  const share: SellerPressureView["share"] = [];
  const supply: SellerPressureView["supply"] = [];
  const price: SellerPressureView["price"] = [];
  for (let i = 0; i < PRESSURE_POINTS; i += 1) {
    const last = i === PRESSURE_POINTS - 1;
    const at = new Date(
      PRESSURE_LAST_AT - (PRESSURE_POINTS - 1 - i) * HOUR_MS,
    ).toISOString();
    const slow = Math.sin(i / 90);
    const fast = Math.sin(i / 7);
    loss.push({
      at,
      lth: last ? 1_983_300 : 2_500_000 + 1_200_000 * slow + 300_000 * fast,
      sth: last ? 8_540_500 : 12_000_000 + 6_000_000 * slow + 800_000 * fast,
      ...V1_POINT,
    });
    share.push({
      at,
      value: last ? 0.41893330324776934 : 0.3 + 0.12 * slow + 0.02 * fast,
      ...V1_POINT,
    });
    supply.push({
      at,
      value: last ? 0.2957342245796155 : 0.28 + 0.01 * slow + 0.002 * fast,
      ...V1_POINT,
    });
    price.push({
      at,
      value: 100_000 + 8_000 * slow + 600 * fast + i * 3,
      ...V1_POINT,
    });
  }
  const lastAt = loss[loss.length - 1].at;
  return {
    data_state: "fresh",
    reasons: [],
    refreshing: false,
    forming_at: lastAt,
    last_at: lastAt,
    loss,
    share,
    supply,
    price,
    loss_levels: { p95: 41_345_525, p75: 10_050_150, n: 716 },
    share_levels: {
      p95: 0.5611976039771673,
      p75: 0.22150410301296825,
      n: 716,
    },
    supply_levels: {
      p95: 0.38687086545521404,
      p75: 0.26151208272764137,
      n: 716,
    },
    xgap: 2,
    qc: [],
    brk_version: "0.1.0",
    rules: [],
    rules_pending: false,
    closed_at: null,
    loss_run: null,
    share_run: null,
    supply_run: null,
  };
}

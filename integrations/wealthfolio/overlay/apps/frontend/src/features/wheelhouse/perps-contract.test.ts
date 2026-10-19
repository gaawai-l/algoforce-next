import { describe, expect, it } from "vitest";
import raw from "./perp-states-sample.json";
import ruledRaw from "./perp-states-sample-ruled.json";
import {
  perpStatesSample,
  perpStatesViewSchema,
  perpsStatusSchema,
  type PerpStatesView,
  type PerpsStatus,
} from "./perps-contract";

const fullSample = () => perpStatesSample();
// Taken before any test runs, to prove no sample or variant ever writes to the import.
const pristine = structuredClone(raw);

// The streams the comparison collectors write: only /perps/status reports them now.
const collector = (stream: PerpsStatus["collectors"][number]["stream"]) => ({
  stream,
  live: true,
  last_proof: "2026-10-17T11:06:54Z",
  down_since: null,
  covered_days: 31.5,
  since: "2026-09-16T00:00:00Z",
  problems: {} as Record<string, number>,
});

function status(): PerpsStatus {
  const check = {
    verdict: "ok" as const,
    samples: 120,
    down: 60,
    long_share: 0.71,
  };
  return {
    last_run_at: "2026-10-17T11:05:04Z",
    last_error: null,
    hosts: [
      {
        host: "fapi.binance.com",
        last_success: "2026-10-17T11:05:04Z",
        error: null,
        backoff_until: null,
      },
      {
        host: "api.bybit.com",
        last_success: null,
        error: "http_429",
        backoff_until: "2026-10-17T11:10:00Z",
      },
    ],
    // The service's counts since it started: the first stream rotated twice and stalled once.
    collectors: (["binance_liq", "bybit_liq", "bybit_trades"] as const).map(
      (stream, k) => ({
        ...collector(stream),
        problems: (k === 0 ? { rotated: 2, stalled: 1 } : {}) as Record<
          string,
          number
        >,
      }),
    ),
    markets: [
      {
        venue: "binance",
        symbol: "BTCUSDT_PERP.A",
        denominated: "BASE_ASSET",
        buy_sell: false,
        ok: true,
      },
      {
        venue: "okx",
        symbol: "BTCUSDT_PERP.3",
        denominated: "USD",
        buy_sell: true,
        ok: false,
      },
      {
        venue: "hyperliquid",
        symbol: "BTC.H",
        denominated: null,
        buy_sell: null,
        ok: false,
      },
    ],
    direction: "ok",
    direction_check: {
      binance: check,
      bybit: check,
      okx: check,
    },
  };
}

describe("perp states contract", () => {
  it("accepts the checked-in service sample", () => {
    const parsed = perpStatesViewSchema.parse(raw);
    expect(parsed.exchange).toBe("all");
    expect(parsed.window).toBe("4h");
    expect(parsed.data_state).toBe("fresh");
    expect(parsed.collecting).toBe(false);
    expect(parsed.thresholds?.n_px).toBe(189);
    expect(parsed.thresholds?.n_oi).toBe(189);
    // The sample is derived under v1: no rules, and no block has thresholds of its own.
    expect([parsed.rules, parsed.rules_pending]).toEqual([[], false]);
    expect(parsed.blocks.every((block) => block.thresholds === null)).toBe(
      true,
    );
    expect(parsed.blocks).toHaveLength(181);
    expect(parsed.blocks.at(-1)?.forming).toBe(true);
    expect(parsed.tables.map((table) => table.show_days)).toEqual([7, 30]);
    // The comparison collectors feed no view, so a view does not list them.
    expect(raw).not.toHaveProperty("collectors");
    expect(ruledRaw).not.toHaveProperty("collectors");
  });

  it("takes Hyperliquid as an exchange", () => {
    const sample = { ...raw, exchange: "hyperliquid" };
    expect(perpStatesViewSchema.parse(sample).exchange).toBe("hyperliquid");
  });

  it("accepts the checked-in O1 and O6 sample, judged in part", () => {
    const parsed = perpStatesViewSchema.parse(ruledRaw);
    expect([parsed.rules, parsed.rules_pending]).toEqual([["O1", "O6"], false]);
    expect(parsed.collecting).toBe(false);
    // The first 43 blocks rank too few blocks before them, block 55 has an imputed OI change
    // and the forming block is only drawn; every block carries its own thresholds.
    expect(parsed.blocks.map((block) => block.state !== null)).toEqual([
      ...Array(43).fill(false),
      ...Array(12).fill(true),
      false,
      ...Array(6).fill(true),
      false,
    ]);
    expect(parsed.blocks.every((block) => block.thresholds !== null)).toBe(
      true,
    );
    expect(parsed.blocks[0].thresholds?.s_liq).toBeNull();
    expect(parsed.blocks[55].imputed.doi).toBe(true);
    expect(parsed.blocks.at(-1)?.forming).toBe(true);
    // The view is headed by the last closed block's thresholds.
    expect(parsed.thresholds).toEqual(parsed.blocks.at(-2)?.thresholds);
    expect(parsed.tables.map((table) => [table.in_view, table.judged])).toEqual(
      [
        [42, 18],
        [63, 18],
      ],
    );
    expect(perpStatesSample("ruled")).toEqual(ruledRaw);
  });

  it("hands out the sample as the file's data, never as shared state", () => {
    const sample = fullSample();
    expect(sample).toEqual(raw);
    sample.blocks[0].state = null;
    sample.tables[0].rows[0].count = 99;
    sample.qc.push("missing:bybit:oi");
    expect(fullSample()).toEqual(raw);
    expect(raw.blocks[0].state).toBe("chop");
    expect(raw.qc).toEqual([]);
  });

  it("derives every variant from the full sample without touching it", () => {
    for (const variant of ["collecting", "uncovered", "qc"] as const) {
      expect(
        perpStatesViewSchema.safeParse(perpStatesSample(variant)).success,
      ).toBe(true);
    }
    expect(raw).toEqual(pristine);
    expect(perpStatesSample("full")).toEqual(pristine);
    expect(perpStatesSample()).toEqual(pristine);
    expect(raw.collecting).toBe(false);
  });

  it("keeps a missing view null and empty instead of zero", () => {
    const empty: PerpStatesView = {
      ...fullSample(),
      data_state: "unavailable",
      reasons: ["series_missing:bybit:oi"],
      computed_at: null,
      last: null,
      thresholds: null,
      blocks: [],
      tail: null,
      tables: [],
      covered_days: null,
      collecting: null,
      qc: [],
      series_missing: [],
    };
    const parsed = perpStatesViewSchema.parse(empty);
    expect(parsed.thresholds).toBeNull();
    expect(parsed.collecting).toBeNull();
    expect(parsed.covered_days).toBeNull();
    expect(parsed.blocks).toEqual([]);
  });

  it("accepts O6 thresholds of a block and null ones whose sample is short", () => {
    const sample = fullSample();
    const own = {
      s_liq: null,
      l_liq: null,
      oi: 280.1,
      px: 0.68,
      n_liq: 40,
      n_px: 49,
      n_oi: 50,
    };
    sample.rules = ["O6"];
    sample.thresholds = own;
    sample.blocks[0] = { ...sample.blocks[0], state: null, thresholds: own };
    const parsed = perpStatesViewSchema.parse(sample);
    expect(parsed.rules).toEqual(["O6"]);
    expect(parsed.thresholds?.s_liq).toBeNull();
    expect(parsed.blocks[0].thresholds).toEqual(own);
  });

  it("accepts a tail, which is drawn but never judged", () => {
    const sample = fullSample();
    sample.tail = {
      t0: "2026-10-17T10:00:00Z",
      t1: "2026-10-17T10:20:00Z",
      price_close: 56_900,
      oi_close: null,
      delta_sum: -1.5,
      lliq_sum: null,
      sliq_sum: 0,
    };
    expect(perpStatesViewSchema.parse(sample).tail?.oi_close).toBeNull();
  });

  it("rejects values outside the contract instead of rendering a guess", () => {
    const sample = fullSample();
    const bad = (patch: object) =>
      perpStatesViewSchema.safeParse({ ...sample, ...patch }).success;
    expect(bad({ data_state: "live" })).toBe(false);
    expect(bad({ exchange: "okx" })).toBe(false);
    expect(bad({ window: "1h" })).toBe(false);
    expect(bad({ last: "2026-10-17T10:50:00" })).toBe(false);
    expect(bad({ computed_at: undefined })).toBe(false);
    expect(bad({ rules: ["O7"] })).toBe(false);
    expect(bad({ rules_pending: undefined })).toBe(false);
    expect(
      bad({ blocks: [{ ...sample.blocks[0], thresholds: undefined }] }),
    ).toBe(false);
    expect(bad({ blocks: [{ ...sample.blocks[0], state: "bull" }] })).toBe(
      false,
    );
    expect(bad({ blocks: [{ ...sample.blocks[0], buckets: 24.5 }] })).toBe(
      false,
    );
    expect(
      bad({
        tables: [
          {
            ...sample.tables[0],
            rows: [{ ...sample.tables[0].rows[0], share: 3.5 }],
          },
        ],
      }),
    ).toBe(false);
  });
});

describe("perp states variants", () => {
  it("collecting: nothing is judged and no share is invented", () => {
    const view = perpStatesViewSchema.parse(perpStatesSample("collecting"));
    expect(view.collecting).toBe(true);
    expect(view.covered_days).toBeLessThan(7);
    expect(view.reasons).toContain(
      `collecting:${view.covered_days?.toFixed(1)}`,
    );
    expect(view.blocks.length).toBeGreaterThan(0);
    expect(view.blocks.every((block) => block.state === null)).toBe(true);
    expect(view.tables).toHaveLength(2);
    for (const table of view.tables) {
      expect(table.judged).toBe(0);
      expect(table.in_view).toBe(view.blocks.length);
      expect(table.latest).toBeNull();
      expect(table.rows.every((row) => row.count === 0)).toBe(true);
      expect(table.rows.every((row) => row.share === null)).toBe(true);
      expect(table.rows.every((row) => row.max_move === null)).toBe(true);
      expect(table.rows.every((row) => row.run_blocks === null)).toBe(true);
    }
    expect(view.thresholds?.n_px).toBe(view.blocks.length);
    expect(view.thresholds?.n_oi).toBe(view.blocks.length);
    expect(perpStatesSample("collecting")).not.toHaveProperty("collectors");
  });

  it("uncovered: blocks without coverage stay unjudged and their sums null", () => {
    const view = perpStatesViewSchema.parse(perpStatesSample("uncovered"));
    const uncovered = view.blocks.filter((block) => !block.covered);
    expect(uncovered.map((block) => block.forming)).toEqual([false, true]);
    for (const block of uncovered) {
      expect(block.liq_covered).toBe(false);
      expect(block.delta_covered).toBe(false);
      expect(block.state).toBeNull();
      expect(block.imputed.sums).toBe(true);
      expect([block.delta_sum, block.lliq_sum, block.sliq_sum]).toEqual([
        null,
        null,
        null,
      ]);
      expect([block.delta, block.lliq, block.sliq]).toEqual([0, 0, 0]);
    }
    expect(view.blocks.filter((block) => block.covered)).toHaveLength(179);
    expect(view.collecting).toBe(false);
    // Coinalyze, where every view reads its liquidations, answered 429.
    expect(view.reasons).toEqual(["rest_error:api.coinalyze.net:429"]);
    // Recounted the way the service does: the forming block was the latest.
    expect(view.thresholds?.n_liq).toBe(187);
    expect(view.covered_days).toBeCloseTo(187 / 6, 10);
    const [week, month] = view.tables;
    expect([week.judged, week.in_view]).toEqual([41, 42]);
    expect([month.judged, month.in_view]).toEqual([179, 180]);
    expect(week.rows.map((row) => row.share)).toEqual([
      3, 5, 7, 5, 7, 7, 15, 51,
    ]);
    expect(month.rows.map((row) => row.share)).toEqual([
      4, 5, 7, 5, 5, 5, 17, 52,
    ]);
    for (const table of view.tables) {
      expect(table.rows.reduce((sum, row) => sum + row.count, 0)).toBe(
        table.judged,
      );
      expect(table.latest).toBeNull();
      expect(table.latest_uncovered).toBe(true);
    }
  });

  it("qc: carries the service's check codes", () => {
    const view = perpStatesViewSchema.parse(perpStatesSample("qc"));
    // The service's order: series by series (missing, then gap), then the archive.
    expect(view.qc).toEqual([
      "gap:binance:oi:3600",
      "missing:bybit:oi",
      "archive_quarantined:1",
    ]);
    expect(view.collecting).toBe(false);
    expect(view.blocks.every((block) => block.state !== null)).toBe(true);
  });
});

describe("perps status contract", () => {
  it("accepts the status payload", () => {
    const parsed = perpsStatusSchema.parse(status());
    expect(parsed.direction).toBe("ok");
    expect(parsed.hosts[1].backoff_until).toBe("2026-10-17T11:10:00Z");
    expect(parsed.direction_check?.okx.verdict).toBe("ok");
    expect(parsed.collectors).toHaveLength(3);
    expect(parsed.collectors[0].problems).toEqual({ rotated: 2, stalled: 1 });
    expect(parsed.collectors[1].problems).toEqual({});
  });

  it("lists the market checks, with null where Coinalyze does not list the symbol", () => {
    const parsed = perpsStatusSchema.parse(status());
    expect(parsed.markets.map((check) => [check.venue, check.ok])).toEqual([
      ["binance", true],
      ["okx", false],
      ["hyperliquid", false],
    ]);
    expect(parsed.markets[2].denominated).toBeNull();
    expect(parsed.markets[2].buy_sell).toBeNull();
  });

  it("keeps a round that has not run yet null", () => {
    const before: PerpsStatus = {
      last_run_at: null,
      last_error: null,
      hosts: [],
      collectors: [],
      markets: [],
      direction: "pending",
      direction_check: null,
    };
    const parsed = perpsStatusSchema.parse(before);
    expect(parsed.last_run_at).toBeNull();
    expect(parsed.direction_check).toBeNull();
    expect(parsed.markets).toEqual([]);
  });

  it("keeps an unchecked venue's long share null, not a failed check", () => {
    const payload = status();
    if (!payload.direction_check) throw new Error("no direction check");
    payload.direction_check.okx = {
      verdict: "pending",
      samples: 0,
      down: 0,
      long_share: null,
    };
    const parsed = perpsStatusSchema.parse(payload);
    expect(parsed.direction_check?.okx.long_share).toBeNull();
    expect(parsed.direction_check?.okx.verdict).toBe("pending");
  });

  it("rejects a verdict, a stream or a market venue outside the contract", () => {
    const payload = status();
    expect(
      perpsStatusSchema.safeParse({
        ...payload,
        markets: [{ ...payload.markets[0], venue: "deribit" }],
      }).success,
    ).toBe(false);
    expect(
      perpsStatusSchema.safeParse({ ...payload, markets: undefined }).success,
    ).toBe(false);
    expect(
      perpsStatusSchema.safeParse({ ...payload, direction: "flipped" }).success,
    ).toBe(false);
    expect(
      perpsStatusSchema.safeParse({
        ...payload,
        collectors: [{ ...payload.collectors[0], stream: "okx_liq" }],
      }).success,
    ).toBe(false);
    expect(
      perpsStatusSchema.safeParse({ ...payload, hosts: undefined }).success,
    ).toBe(false);
    // A count is a whole number, and the counts are always there, if empty.
    for (const problems of [{ stalled: 1.5 }, undefined])
      expect(
        perpsStatusSchema.safeParse({
          ...payload,
          collectors: [{ ...payload.collectors[0], problems }],
        }).success,
      ).toBe(false);
  });
});

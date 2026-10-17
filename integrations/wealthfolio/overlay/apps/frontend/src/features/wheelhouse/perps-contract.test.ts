import { describe, expect, it } from "vitest";
import raw from "./perp-states-sample.json";
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

function status(view: PerpStatesView): PerpsStatus {
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
    collectors: view.collectors.map((collector, k) => ({
      ...collector,
      problems: (k === 0 ? { rotated: 2, stalled: 1 } : {}) as Record<
        string,
        number
      >,
    })),
    direction: "ok",
    direction_check: {
      binance: check,
      bybit: check,
      bybit_qty: {
        events: 40,
        min_qty: 0.001,
        min_notional: 60,
        max_notional: 250_000,
        notional_in_range: true,
        min_qty_matches: true,
      },
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
    expect(parsed.thresholds?.n_all).toBe(189);
    expect(parsed.blocks).toHaveLength(181);
    expect(parsed.blocks.at(-1)?.forming).toBe(true);
    expect(parsed.tables.map((table) => table.show_days)).toEqual([7, 30]);
    expect(parsed.collectors.map((c) => c.stream)).toEqual([
      "binance_liq",
      "bybit_liq",
      "bybit_trades",
    ]);
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
    expect(bad({ collectors: undefined })).toBe(false);
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
    expect(
      bad({
        collectors: [{ ...sample.collectors[0], stream: "okx_liq" }],
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
    expect(view.thresholds?.n_all).toBe(view.blocks.length);
    // The streams started with the first block, so they cover what the view covers.
    for (const collector of view.collectors) {
      expect(collector.live).toBe(true);
      expect(collector.covered_days).toBe(view.covered_days);
      expect(collector.since).toBe(view.blocks[0].t0);
    }
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
    // Every stream went down inside the forming block, after a past gap over the oldest block:
    // 32 h before the gap and 717.5 h after it.
    expect(view.reasons).toEqual([
      "collector_down:binance_liq",
      "collector_down:bybit_liq",
      "collector_down:bybit_trades",
    ]);
    const formingStart = Date.parse(uncovered[1].t0);
    for (const collector of view.collectors) {
      expect(collector.live).toBe(false);
      expect(collector.down_since).toBe(collector.last_proof);
      expect(Date.parse(collector.down_since ?? "")).toBeGreaterThan(
        formingStart,
      );
      expect(collector.covered_days).toBeCloseTo(749.5 / 24, 10);
      expect(collector.since).toBe(fullSample().collectors[0].since);
    }
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
    const parsed = perpsStatusSchema.parse(status(fullSample()));
    expect(parsed.direction).toBe("ok");
    expect(parsed.hosts[1].backoff_until).toBe("2026-10-17T11:10:00Z");
    expect(parsed.direction_check?.bybit_qty.events).toBe(40);
    expect(parsed.collectors).toHaveLength(3);
    expect(parsed.collectors[0].problems).toEqual({ rotated: 2, stalled: 1 });
    expect(parsed.collectors[1].problems).toEqual({});
  });

  it("keeps a round that has not run yet null", () => {
    const before: PerpsStatus = {
      last_run_at: null,
      last_error: null,
      hosts: [],
      collectors: [],
      direction: "pending",
      direction_check: null,
    };
    const parsed = perpsStatusSchema.parse(before);
    expect(parsed.last_run_at).toBeNull();
    expect(parsed.direction_check).toBeNull();
  });

  it("keeps an unchecked Bybit size unit null, not a failed check", () => {
    const payload = status(fullSample());
    if (!payload.direction_check) throw new Error("no direction check");
    payload.direction_check.bybit_qty = {
      events: 0,
      min_qty: null,
      min_notional: null,
      max_notional: null,
      notional_in_range: null,
      min_qty_matches: null,
    };
    const parsed = perpsStatusSchema.parse(payload);
    expect(parsed.direction_check?.bybit_qty.notional_in_range).toBeNull();
  });

  it("rejects a verdict or a stream outside the contract", () => {
    const payload = status(fullSample());
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

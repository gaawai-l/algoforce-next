import { describe, expect, it } from "vitest";
import {
  costBasisSample,
  costBasisViewSchema,
  cycleSample,
  cycleViewSchema,
  levelsSample,
  levelsViewSchema,
  pressureSample,
  sellerPressureSchema,
} from "./onchain-contract";

describe("on-chain cycle contract", () => {
  it("accepts the service payload", () => {
    const parsed = cycleViewSchema.parse(cycleSample);
    expect(parsed.state).toBe("breakout");
    expect(parsed.day).toBe(24);
    expect(parsed.changes).toBe(48);
    expect(parsed.components).toHaveLength(3);
    expect(parsed.components.map((component) => component.supports)).toEqual([
      true,
      true,
      true,
    ]);
    expect(parsed.components[2].value).toBeLessThan(0);
    expect(parsed.refreshing).toBe(false);
  });

  it("keeps a missing cycle null instead of coercing it to zero", () => {
    const empty = {
      ...cycleSample,
      data_state: "unavailable",
      reasons: ["brk_unavailable"],
      forming_at: null,
      as_of: null,
      state: null,
      since: null,
      day: null,
      components: [],
      episodes: [],
      changes: null,
      brk_version: null,
    };
    const parsed = cycleViewSchema.parse(empty);
    expect(parsed.changes).toBeNull();
    expect(parsed.day).toBeNull();
  });

  it("rejects an unknown cycle state instead of rendering a guess", () => {
    expect(
      cycleViewSchema.safeParse({ ...cycleSample, state: "bull" }).success,
    ).toBe(false);
  });

  it("rejects a malformed date or a datetime without an offset", () => {
    expect(
      cycleViewSchema.safeParse({ ...cycleSample, since: "2026-9-23" }).success,
    ).toBe(false);
    expect(
      cycleViewSchema.safeParse({
        ...cycleSample,
        forming_at: "2026-10-16T00:00:00",
      }).success,
    ).toBe(false);
  });

  it("rejects an unknown component name or data state", () => {
    const badComponent = {
      ...cycleSample,
      components: [{ ...cycleSample.components[0], name: "momentum" }],
    };
    expect(cycleViewSchema.safeParse(badComponent).success).toBe(false);
    expect(
      cycleViewSchema.safeParse({ ...cycleSample, data_state: "live" }).success,
    ).toBe(false);
  });
});

describe("on-chain levels contract", () => {
  it("accepts the service payload", () => {
    const parsed = levelsViewSchema.parse(levelsSample);
    expect(parsed.lines).toHaveLength(5);
    expect(parsed.onchain_close).toBe(112_345.67);
  });

  it("accepts exactly the five model line names", () => {
    for (const name of [
      "true_mean",
      "short_term",
      "average",
      "long_term",
      "median",
    ]) {
      const next = { ...levelsSample, lines: [{ name, price: 100 }] };
      expect(levelsViewSchema.safeParse(next).success).toBe(true);
    }
    const bad = { ...levelsSample, lines: [{ name: "realized", price: 100 }] };
    expect(levelsViewSchema.safeParse(bad).success).toBe(false);
  });

  it("keeps an unavailable snapshot null instead of coercing it to zero", () => {
    const empty = {
      ...levelsSample,
      data_state: "unavailable",
      reasons: ["urpd_missing"],
      forming_at: null,
      as_of: null,
      urpd_date: null,
      onchain_close: null,
      lines: [],
      brk_version: null,
    };
    const parsed = levelsViewSchema.parse(empty);
    expect(parsed.onchain_close).toBeNull();
    expect(parsed.urpd_date).toBeNull();
  });
});

describe("on-chain seller pressure contract", () => {
  it("accepts the sample payload", () => {
    const sample = pressureSample();
    const parsed = sellerPressureSchema.parse(sample);
    for (const series of [
      parsed.loss,
      parsed.share,
      parsed.supply,
      parsed.price,
    ]) {
      expect(series).toHaveLength(2200);
    }
    expect(parsed.data_state).toBe("fresh");
    expect(parsed.qc).toEqual([]);
    expect(parsed.last_at).toBe(parsed.forming_at);
    expect(parsed.loss.at(-1)).toMatchObject({
      lth: 1_983_300,
      sth: 8_540_500,
    });
    expect(parsed.share.at(-1)?.value).toBe(0.41893330324776934);
    expect(parsed.supply.at(-1)?.value).toBe(0.2957342245796155);
    expect(parsed.loss_levels).toEqual({
      p95: 41_345_525,
      p75: 10_050_150,
      n: 716,
    });
    expect(parsed.share_levels).toEqual({
      p95: 0.5611976039771673,
      p75: 0.22150410301296825,
      n: 716,
    });
    expect(parsed.supply_levels).toEqual({
      p95: 0.38687086545521404,
      p75: 0.26151208272764137,
      n: 716,
    });
  });

  it("builds consecutive UTC hourly points ending at the forming hour", () => {
    const sample = pressureSample();
    const times = sample.loss.map((point) => Date.parse(point.at));
    expect(sample.loss.at(-1)?.at).toBe("2026-10-16T08:00:00.000Z");
    expect(sample.forming_at).toBe(sample.loss.at(-1)?.at);
    for (let i = 1; i < times.length; i += 1)
      expect(times[i] - times[i - 1]).toBe(3_600_000);
    for (const series of [sample.share, sample.supply, sample.price])
      expect(series.map((point) => point.at)).toEqual(
        sample.loss.map((point) => point.at),
      );
    expect(pressureSample()).toEqual(sample);
  });

  it("accepts a delayed snapshot", () => {
    const parsed = sellerPressureSchema.parse({
      ...pressureSample(),
      data_state: "delayed",
      reasons: ["hour1_lag"],
    });
    expect(parsed.data_state).toBe("delayed");
  });

  it("rejects an unknown data state", () => {
    expect(
      sellerPressureSchema.safeParse({
        ...pressureSample(),
        data_state: "live",
      }).success,
    ).toBe(false);
  });

  it("accepts the known QC codes and rejects any other", () => {
    const qc = ["hour_gap", "intraday_legs", "sth_supply"];
    expect(sellerPressureSchema.parse({ ...pressureSample(), qc }).qc).toEqual(
      qc,
    );
    expect(
      sellerPressureSchema.safeParse({ ...pressureSample(), qc: ["aligned"] })
        .success,
    ).toBe(false);
  });

  it("keeps an unavailable snapshot null instead of coercing it to zero", () => {
    const empty = {
      data_state: "unavailable",
      reasons: ["brk_unavailable"],
      refreshing: false,
      forming_at: null,
      last_at: null,
      loss: [],
      share: [],
      supply: [],
      price: [],
      loss_levels: null,
      share_levels: null,
      supply_levels: null,
      xgap: null,
      qc: [],
      brk_version: null,
    };
    const parsed = sellerPressureSchema.parse(empty);
    expect(parsed.loss_levels).toBeNull();
    expect(parsed.xgap).toBeNull();
    expect(parsed.last_at).toBeNull();
    const nullLevel = sellerPressureSchema.parse({
      ...pressureSample(),
      share_levels: { p95: null, p75: null, n: 0 },
    });
    expect(nullLevel.share_levels?.p95).toBeNull();
  });

  it("rejects a point with a missing value or a datetime without an offset", () => {
    const sample = pressureSample();
    expect(
      sellerPressureSchema.safeParse({
        ...sample,
        share: [{ at: "2026-10-16T08:00:00Z" }],
      }).success,
    ).toBe(false);
    expect(
      sellerPressureSchema.safeParse({
        ...sample,
        loss: [{ at: "2026-10-16T08:00:00", lth: 1, sth: 1 }],
      }).success,
    ).toBe(false);
  });
});

describe("on-chain cost basis contract", () => {
  const bucket = (width: number) => {
    const found = costBasisSample.buckets.find((item) => item.bucket === width);
    if (!found) throw new Error(`no ${width} bucket in the sample`);
    return found;
  };

  it("accepts the sample payload", () => {
    const parsed = costBasisViewSchema.parse(costBasisSample);
    expect(parsed.data_state).toBe("fresh");
    expect(parsed.reasons).toEqual([]);
    expect(parsed.refreshing).toBe(false);
    expect(parsed.urpd_date).toBe("2026-10-16");
    expect(parsed.lines_as_of).toBe("2026-10-16");
    expect(parsed.snapshot_at).toBe("2026-10-16T18:29:40Z");
    expect(parsed.forming_at).toBe("2026-10-16T00:00:00Z");
    expect(parsed.brk_version).toBe("0.12.2");
    expect(parsed.buckets.map((item) => item.bucket)).toEqual([200, 500, 1000]);
  });

  it("carries the 2026-10-16 golden prices exactly", () => {
    const peaks = (width: number, cohort: "sth" | "lth") =>
      bucket(width)[cohort].peaks.map((peak) => peak.price);
    expect(peaks(200, "sth")).toEqual([63500, 82300]);
    expect(peaks(500, "sth")).toEqual([63750, 82250]);
    expect(peaks(1000, "sth")).toEqual([63500, 82500]);
    expect(peaks(200, "lth")).toEqual([6900, 39100, 67300, 84900, 108100]);
    expect(peaks(500, "lth")).toEqual([6750, 38750, 67250, 84750, 108250]);
    expect(peaks(1000, "lth")).toEqual([7500, 39500, 67500, 85500, 108500]);
    expect(bucket(200).resistance).toEqual([86000, 88000, 96000, 104000]);
    expect(bucket(500).resistance).toEqual([86000, 88000, 96000, 104000]);
    expect(bucket(1000).resistance).toEqual([86000, 90000, 96000, 104000]);
    for (const width of [200, 500, 1000])
      expect(bucket(width).support).toEqual([76000, 74000, 70000, 64000]);
    for (const item of costBasisSample.buckets) {
      expect(item.spot).toBe(81217.6);
      expect(item.domain_low).toBe(1000);
    }
    expect(bucket(200).domain_high).toBe(125800);
    expect(bucket(500).domain_high).toBe(126000);
  });

  it("lists the nearest bands first, 2000 wide, with resistance and support at their edges", () => {
    for (const item of costBasisSample.buckets) {
      expect(item.above).toHaveLength(4);
      expect(item.below).toHaveLength(4);
      const bands = [...item.above, ...item.below];
      for (const band of bands) {
        expect(band.high - band.low).toBe(2000);
        expect(band.low % 4000 === 0 || band.high % 4000 === 0).toBe(true);
        expect(band.candidates.length).toBeGreaterThan(0);
        for (const candidate of band.candidates) {
          expect(candidate.price).toBeGreaterThanOrEqual(band.low);
          expect(candidate.price).toBeLessThan(band.high);
        }
      }
      expect(item.above.every((band) => band.low >= item.spot)).toBe(true);
      expect(item.below.every((band) => band.high <= item.spot)).toBe(true);
      expect(item.resistance).toEqual(item.above.map((band) => band.high));
      expect(item.support).toEqual(item.below.map((band) => band.low));
      // Nearest first: above climbs away from spot, below falls away from it.
      for (let i = 1; i < item.above.length; i += 1)
        expect(item.above[i].low).toBeGreaterThan(item.above[i - 1].low);
      for (let i = 1; i < item.below.length; i += 1)
        expect(item.below[i].high).toBeLessThan(item.below[i - 1].high);
    }
  });

  it("describes a candidate by its kind: a model line or a cluster component edge", () => {
    const candidates = costBasisSample.buckets.flatMap((item) =>
      [...item.above, ...item.below].flatMap((band) => band.candidates),
    );
    const lines = candidates.filter((candidate) => candidate.kind === "line");
    const components = candidates.filter(
      (candidate) => candidate.kind === "component",
    );
    expect(lines.length).toBeGreaterThan(0);
    expect(components.length).toBeGreaterThan(0);
    for (const candidate of lines) {
      expect(candidate.line).not.toBeNull();
      expect(candidate.cohort).toBeNull();
      expect(candidate.index).toBeNull();
      expect(candidate.edge).toBeNull();
    }
    for (const candidate of components) {
      expect(candidate.line).toBeNull();
      expect(["sth", "lth"]).toContain(candidate.cohort);
      expect(candidate.index).toBeGreaterThanOrEqual(1);
      expect(["low", "mid", "high"]).toContain(candidate.edge);
    }
  });

  it("rejects a payload with a missing field", () => {
    const { refreshing: _refreshing, ...noRefreshing } = costBasisSample;
    expect(costBasisViewSchema.safeParse(noRefreshing).success).toBe(false);
    const { brk_version: _version, ...noVersion } = costBasisSample;
    expect(costBasisViewSchema.safeParse(noVersion).success).toBe(false);
    const { resistance: _resistance, ...noResistance } = bucket(500);
    expect(
      costBasisViewSchema.safeParse({
        ...costBasisSample,
        buckets: [noResistance],
      }).success,
    ).toBe(false);
    const { edge: _edge, ...noEdge } = bucket(500).above[0].candidates[0];
    expect(
      costBasisViewSchema.safeParse({
        ...costBasisSample,
        buckets: [
          {
            ...bucket(500),
            above: [{ ...bucket(500).above[0], candidates: [noEdge] }],
          },
        ],
      }).success,
    ).toBe(false);
    const { sigma: _sigma, ...noSigma } = bucket(500).sth.components[0];
    expect(
      costBasisViewSchema.safeParse({
        ...costBasisSample,
        buckets: [
          {
            ...bucket(500),
            sth: { ...bucket(500).sth, components: [noSigma] },
          },
        ],
      }).success,
    ).toBe(false);
  });

  it("rejects an unknown bucket width, cohort, line name or data state", () => {
    const withBucket = (patch: object) => ({
      ...costBasisSample,
      buckets: [{ ...bucket(500), ...patch }],
    });
    expect(
      costBasisViewSchema.safeParse(withBucket({ bucket: 300 })).success,
    ).toBe(false);
    expect(
      costBasisViewSchema.safeParse(
        withBucket({ sth: { ...bucket(500).sth, cohort: "all" } }),
      ).success,
    ).toBe(false);
    const badLine = {
      ...bucket(500).above[0].candidates[0],
      kind: "line",
      line: "realized",
    };
    expect(
      costBasisViewSchema.safeParse(
        withBucket({
          above: [{ ...bucket(500).above[0], candidates: [badLine] }],
        }),
      ).success,
    ).toBe(false);
    expect(
      costBasisViewSchema.safeParse({ ...costBasisSample, data_state: "live" })
        .success,
    ).toBe(false);
    expect(
      costBasisViewSchema.safeParse({
        ...costBasisSample,
        data_state: "delayed",
      }).success,
    ).toBe(false);
  });

  it("rejects an unknown candidate kind, edge or cohort", () => {
    const band = bucket(500).above[0];
    const component = bucket(500)
      .above.flatMap((item) => item.candidates)
      .find((candidate) => candidate.kind === "component");
    if (!component) throw new Error("no component candidate in the sample");
    const withCandidate = (patch: object) => ({
      ...costBasisSample,
      buckets: [
        {
          ...bucket(500),
          above: [{ ...band, candidates: [{ ...component, ...patch }] }],
        },
      ],
    });
    expect(costBasisViewSchema.safeParse(withCandidate({})).success).toBe(true);
    for (const patch of [{ kind: "peak" }, { edge: "top" }, { cohort: "all" }])
      expect(costBasisViewSchema.safeParse(withCandidate(patch)).success).toBe(
        false,
      );
  });

  it("rejects a malformed date or a datetime without an offset", () => {
    expect(
      costBasisViewSchema.safeParse({
        ...costBasisSample,
        urpd_date: "2026-10-6",
      }).success,
    ).toBe(false);
    expect(
      costBasisViewSchema.safeParse({
        ...costBasisSample,
        snapshot_at: "2026-10-16T18:29:40",
      }).success,
    ).toBe(false);
  });

  it("keeps an unavailable snapshot null instead of coercing it to zero", () => {
    const empty = {
      data_state: "unavailable",
      reasons: ["urpd_missing"],
      refreshing: false,
      forming_at: null,
      urpd_date: null,
      lines_as_of: null,
      snapshot_at: null,
      computed_at: null,
      buckets: [],
      brk_version: null,
    };
    const parsed = costBasisViewSchema.parse(empty);
    expect(parsed.buckets).toEqual([]);
    expect(parsed.urpd_date).toBeNull();
    expect(parsed.snapshot_at).toBeNull();
  });

  it("keeps a missing share in profit null instead of coercing it to zero", () => {
    const parsed = costBasisViewSchema.parse({
      ...costBasisSample,
      buckets: [
        {
          ...bucket(500),
          lth: { ...bucket(500).lth, in_profit: null, peaks: [] },
        },
      ],
    });
    expect(parsed.buckets[0].lth.in_profit).toBeNull();
  });
});

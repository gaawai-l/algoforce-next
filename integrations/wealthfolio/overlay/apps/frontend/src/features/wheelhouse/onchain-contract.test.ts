import { describe, expect, it } from "vitest";
import {
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

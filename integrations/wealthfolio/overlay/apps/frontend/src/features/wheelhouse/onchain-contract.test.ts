import { describe, expect, it } from "vitest";
import {
  cycleSample,
  cycleViewSchema,
  levelsSample,
  levelsViewSchema,
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

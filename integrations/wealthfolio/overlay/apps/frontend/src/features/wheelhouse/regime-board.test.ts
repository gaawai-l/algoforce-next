import { describe, expect, it } from "vitest";
import { regimeSideFor, shortAge, signalLevel } from "./regime-board";

const signal = {
  n: 1 as const,
  side: "buy" as const,
  active: true,
  price: "1",
  base_level: 2,
  intraday_level: 3,
  swing_level: 1,
};

describe("AlphaBTC board mapping", () => {
  it("uses one regime per single board and splits the all board", () => {
    expect(regimeSideFor("cta", "4h")).toBe("intraday");
    expect(regimeSideFor("opt", "5m")).toBe("swing");
    expect(regimeSideFor("all", "1h")).toBe("intraday");
    expect(regimeSideFor("all", "4h")).toBe("swing");
  });

  it("returns the calibrated or base level and nothing for inactive signals", () => {
    expect(signalLevel(signal, "intraday", true)).toBe(3);
    expect(signalLevel(signal, "swing", true)).toBe(1);
    expect(signalLevel(signal, "intraday", false)).toBe(2);
    expect(signalLevel({ ...signal, active: false }, "intraday", true)).toBeNull();
  });

  it("formats ages like AlphaBTC's short clock", () => {
    expect(shortAge(1200)).toBe("<1h");
    expect(shortAge(12 * 3600)).toBe("12h");
    expect(shortAge(4 * 86400)).toBe("4D");
    expect(shortAge(null)).toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import { marketContextSchema } from "./regime-contract";
import { sampleContext } from "./regime-sample";

describe("market context contract", () => {
  it("accepts the service payload", () => {
    const parsed = marketContextSchema.parse(sampleContext);
    expect(parsed.intraday.value).toBe("pump");
    expect(parsed.timeframes[2].signals[1].intraday_level).toBe(4);
  });

  it("rejects an unknown regime instead of rendering a guess", () => {
    const bad = { ...sampleContext, intraday: { anchor: "1h", value: "bullish" } };
    expect(marketContextSchema.safeParse(bad).success).toBe(false);
  });
});

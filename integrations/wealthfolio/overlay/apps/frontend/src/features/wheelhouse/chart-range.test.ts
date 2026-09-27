import { expect, it } from "vitest";
import { defaultBarCount, fridayWindow } from "./chart-range";
it("uses timeframe and width instead of imposing a 200-bar ceiling", () => {
  expect(defaultBarCount("15m", 800, 500)).toBe(160);
  expect(defaultBarCount("15m", 1200, 500)).toBe(240);
  expect(defaultBarCount("15m", 2500, 500)).toBe(360);
  expect(defaultBarCount("4h", 400, 500)).toBe(120);
  expect(defaultBarCount("1h", 400, 50)).toBe(50);
});
it("anchors Fri–Fri at Friday 09:00 UTC+8 without using the system clock", () => {
  const span = fridayWindow(Date.parse("2026-09-28T00:00:00Z"));
  expect(new Date(span.to).toISOString()).toBe("2026-09-25T01:00:00.000Z");
  expect(new Date(span.from).toISOString()).toBe("2026-09-18T01:00:00.000Z");
  expect(
    new Date(fridayWindow(Date.parse("2026-09-25T00:00:00Z")).to).toISOString(),
  ).toBe("2026-09-18T01:00:00.000Z");
});

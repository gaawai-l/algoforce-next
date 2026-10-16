import { describe, expect, it } from "vitest";
import { messages, phrase } from "./i18n";

describe("wheelhouse copy", () => {
  it("keeps Simplified Chinese aligned with English", () => {
    expect(Object.keys(messages.zh).sort()).toEqual(Object.keys(messages.en).sort());
    for (const key of Object.keys(messages.en)) {
      expect(messages.zh[key as keyof typeof messages.zh].length).toBeGreaterThan(0);
    }
  });

  it("keeps the confirmed English market title and translates it", () => {
    expect(phrase("en", "page.title")).toBe("Market intelligence");
    expect(phrase("zh", "page.title")).toBe("市场分析");
    expect(phrase("en", "chart.closedCount", { tf: "5M", count: 639 })).toBe(
      "5M · 639 closed bars",
    );
  });
});

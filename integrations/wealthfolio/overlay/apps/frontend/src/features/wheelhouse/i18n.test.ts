import { describe, expect, it } from "vitest";
import { messages, phrase } from "./i18n";

describe("wheelhouse copy", () => {
  it("keeps Simplified Chinese aligned with English", () => {
    expect(Object.keys(messages.zh).sort()).toEqual(Object.keys(messages.en).sort());
    for (const key of Object.keys(messages.en)) {
      expect(messages.zh[key as keyof typeof messages.zh].length).toBeGreaterThan(0);
    }
  });

  it("carries the Coinalyze copy of the perp states page in both languages", () => {
    const copy = {
      "perp.meta": [
        "Resolution 10m · Data through {{time}} UTC · Price Bybit spot · OI Binance and Bybit (public), OKX and Hyperliquid (Coinalyze)",
        "粒度 10m · 数据截至 {{time}} UTC · 价格 Bybit 现货 · OI：Binance、Bybit（公开接口），OKX、Hyperliquid（Coinalyze）",
      ],
      "perp.source": [
        "Liquidations and buy/sell volume (except Binance's): ",
        "清算与主动买卖量（Binance 的买卖量除外）：",
      ],
      "perp.coverage": [
        "Liquidation history: {{days}} d covered in the last 90",
        "清算历史：近 90 天覆盖 {{days}} 天",
      ],
      "perp.collecting": [
        "Liquidation history too short · {{days}} of 7 days (target 90)",
        "清算历史不足 · 已覆盖 {{days}} / 7 天（目标 90 天）",
      ],
      "perp.hlNote": [
        "Hyperliquid liquidations are estimated: All venues' liquidations scaled by Hyperliquid's OI relative to theirs",
        "Hyperliquid 的清算是估算值：全部交易所的清算 × Hyperliquid OI 与它们 OI 之比",
      ],
      "perp.estimated": ["{{label}} (estimated)", "{{label}}（估算）"],
      "perp.reason.keyMissing": [
        "Coinalyze API key not set: liquidations and Coinalyze flows unavailable",
        "未设置 Coinalyze API key：清算和来自 Coinalyze 的数据不可用",
      ],
      "perp.reason.keyInvalid": [
        "Coinalyze rejected the API key: liquidations and Coinalyze flows unavailable",
        "Coinalyze 拒绝了 API key：清算和来自 Coinalyze 的数据不可用",
      ],
      "perp.reason.units": [
        "Coinalyze {{venue}} market check failed: its data is left out",
        "Coinalyze 的 {{venue}} 市场核对未通过，已停用其数据",
      ],
      "perp.series.okxOi": ["OKX OI", "OKX OI"],
      "perp.series.hyperliquidOi": ["Hyperliquid OI", "Hyperliquid OI"],
    } as const;
    for (const [key, [en, zh]] of Object.entries(copy)) {
      expect(messages.en[key as keyof typeof messages.en], key).toBe(en);
      expect(messages.zh[key as keyof typeof messages.zh], key).toBe(zh);
    }
    expect(phrase("en", "perp.estimated", { label: "Liquidations" })).toBe(
      "Liquidations (estimated)",
    );
    expect(phrase("zh", "perp.estimated", { label: "清算" })).toBe("清算（估算）");
  });

  it("carries the size cohorts copy in both languages", () => {
    const copy = {
      "flows.sizes": ["Size cohorts", "规模分组"],
      "sizes.supply.title": [
        "Chart 5 — Net Supply Change By Size Cohorts",
        "图 5 — 按地址规模分组的净供应变化",
      ],
      "sizes.pnl.title": [
        "Chart 6 — Net Realized Profit & Loss By Size Cohorts",
        "图 6 — 按地址规模分组的净已实现盈亏",
      ],
      "sizes.noBlock": [
        "No block was mined in the hour this {{win}} window starts from, so there is nothing to compare against. It fills in at the next hourly refresh.",
        "这个 {{win}} 窗口起点那一小时没有出块，没有可比的值；下一次每小时刷新后会补上。",
      ],
    } as const;
    for (const [key, [en, zh]] of Object.entries(copy)) {
      expect(messages.en[key as keyof typeof messages.en], key).toBe(en);
      expect(messages.zh[key as keyof typeof messages.zh], key).toBe(zh);
    }
  });

  it("ends the source line so the Coinalyze link follows it without a gap", () => {
    // The line renders as the string followed by the link, with no space between them.
    expect(`${messages.en["perp.source"]}Coinalyze`).toBe(
      "Liquidations and buy/sell volume (except Binance's): Coinalyze",
    );
    expect(`${messages.zh["perp.source"]}Coinalyze`).toBe(
      "清算与主动买卖量（Binance 的买卖量除外）：Coinalyze",
    );
  });

  it("names missing data, not collection, as the cause of the chart hatching", () => {
    for (const key of ["perp.c1.shows", "perp.c4.shows"] as const) {
      expect(messages.en[key], key).toMatch(/hatching[^.]*missing/);
      expect(messages.en[key], key).not.toMatch(/collect/i);
      expect(messages.zh[key], key).toMatch(/缺少/);
      expect(messages.zh[key], key).not.toMatch(/采集/);
    }
  });

  it("no longer has the copy of the self-collected liquidations", () => {
    const gone = [
      "perp.collectingTrades",
      "perp.coverageDays",
      "perp.reason.collectorDown",
      "perp.reason.collectorNever",
    ];
    for (const key of Object.keys(messages.en))
      expect(gone.includes(key) || key.startsWith("perp.stream."), key).toBe(
        false,
      );
  });

  it("keeps the confirmed English market title and translates it", () => {
    expect(phrase("en", "page.title")).toBe("Market intelligence");
    expect(phrase("zh", "page.title")).toBe("市场分析");
    expect(phrase("en", "chart.closedCount", { tf: "5M", count: 639 })).toBe(
      "5M · 639 closed bars",
    );
  });
});

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
      // The window's start has to move past the hour without a block, which takes another hour
      // when the newest hour has no block yet either (the final review's M2).
      "sizes.noBlock": [
        "No block was mined in the hour this {{win}} window starts from, so there is nothing to compare against. It usually fills in within an hour or two, once the window's start moves past that hour.",
        "这个 {{win}} 窗口起点那一小时没有出块，没有可比的值；通常一两个小时内、窗口起点移过这一小时后就会补上。",
      ],
      // Bands switches to the twelve size bands, not to groups (OP-4).
      "sizes.bands": ["Bands", "区间"],
      // A row is a band under Bands and a group under Entities: "档" names either (OP-4).
      "sizes.pctBand": ["% of band", "占本档比例"],
      "sizes.supply.share": ["Share of band", "占本档比例"],
      "sizes.supply.held": ["Band supply", "本档持币量"],
      "sizes.pnl.none": ["no coins from this band moved", "该档没有币移动"],
      // Realized cap is what the band paid for everything it holds, not only for what it spent.
      "sizes.pnl.implies": [
        "This chart sets no thresholds. A band booking mostly losses is spending coins below what it paid for them; one booking mostly profits is spending them into strength. BRK books every on-chain spend, moves between a holder's own wallets included, so booked is not the same as sold. Against realized cap a bar reads as a share of what the band paid for everything it holds.",
        "本图没有设阈值。某区间以亏损入账为主，说明它花费的币低于买入成本；以盈利入账为主，说明它在逢高花费。BRK 记录每一笔链上花费，包括持有者在自己钱包之间的转移，所以“入账”不等于“卖出”。按已实现市值看，条形可理解为占该档全部持币买入成本的比例。",
      ],
    } as const;
    for (const [key, [en, zh]] of Object.entries(copy)) {
      expect(messages.en[key as keyof typeof messages.en], key).toBe(en);
      expect(messages.zh[key as keyof typeof messages.zh], key).toBe(zh);
    }
    // No zh size-cohort line calls a row "this group": under Bands it is a band.
    for (const [key, zh] of Object.entries(messages.zh))
      if (key.startsWith("sizes.")) expect(zh, key).not.toMatch(/本组|该组/);
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

  it("says why Chart 8's backfill waits, in both languages", () => {
    // backfill_error is a BRK code, and the next round's backfill comes with the next hourly
    // refresh; last_error may be sync_failed, and a retryable failure retries in 5 minutes.
    expect(phrase("en", "cbh.paused", { code: "brk_unavailable" })).toBe(
      "history fetch paused: BRK returned brk_unavailable; retrying next hour",
    );
    expect(phrase("zh", "cbh.paused", { code: "brk_unavailable" })).toBe(
      "历史回填暂停：BRK 返回 brk_unavailable，下一小时重试",
    );
    expect(phrase("en", "cbh.held", { code: "sync_failed" })).toBe(
      "history fetch paused: the last refresh failed (sync_failed); it resumes after the next successful refresh",
    );
    expect(phrase("zh", "cbh.held", { code: "sync_failed" })).toBe(
      "历史回填暂停：上一轮刷新失败（sync_failed），下一次刷新成功后继续",
    );
    for (const locale of ["en", "zh"] as const) {
      expect(messages[locale]["cbh.held"]).not.toMatch(/BRK|hour|小时/);
    }
    expect(phrase("en", "cbh.noneStored")).toBe(
      "None of the days in view has a stored snapshot: missing, not zero",
    );
    expect(phrase("zh", "cbh.noneStored")).toBe("视图内没有任何一天存有快照：表示缺失，不是 0");
  });

  it("names Chart 8's controls in Chinese where its Chinese copy refers to them", () => {
    const controls = {
      "cbh.span": "时间跨度",
      "cbh.range": "价格范围",
      "cbh.contrast": "对比度",
      "cbh.all": "全部",
      "cbh.reset": "还原缩放",
      "cbh.belowFloor": "低于下限",
    } as const;
    for (const [key, name] of Object.entries(controls))
      expect(messages.zh[key as keyof typeof controls]).toBe(name);
    for (const name of ["时间跨度", "价格范围", "对比度", "“全部”", "“还原缩放”"])
      expect(messages.zh["cbh.how"]).toContain(name);
    expect(messages.zh["cbh.lower"]).toContain("“低于下限”");
    for (const key of ["cbh.how", "cbh.lower", "cbh.upper", "cbh.aria", "cbh.caption"] as const)
      expect(messages.zh[key], key).not.toMatch(/Span|Range|Contrast|Reset zoom|\bAll\b/);
  });

  it("keeps the confirmed English market title and translates it", () => {
    expect(phrase("en", "page.title")).toBe("Market intelligence");
    expect(phrase("zh", "page.title")).toBe("市场分析");
    expect(phrase("en", "chart.closedCount", { tf: "5M", count: 639 })).toBe(
      "5M · 639 closed bars",
    );
  });
});

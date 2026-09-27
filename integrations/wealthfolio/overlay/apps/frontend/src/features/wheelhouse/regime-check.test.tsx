import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Rules, Stream } from "./client";
import { defaultDemarkConfig } from "./demark-contract";
import { messages } from "./i18n";
import { RegimeCheck } from "./regime-check";
import { sampleContext } from "./regime-sample";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const stream = {
  source: "binance",
  symbol: "BTCUSDT",
  timeframe: "5m",
  venue: "binance-spot",
  market_session: "24/7",
  timezone: "UTC",
  quote_currency: "USDT",
  base_currency: "BTC",
  price_encoding: "decimal_string_18_places",
} as Stream;
const rules: Rules = { engine_version: "baseline-v1", window: 20, demark: defaultDemarkConfig };

it("shows regimes, calibrated levels and unavailable timeframes without guessing", async () => {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) =>
    url.includes("/market-context")
      ? new Response(JSON.stringify(sampleContext))
      : new Response(JSON.stringify({}), { status: 500 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RegimeCheck stream={stream} rules={rules} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText(/Selloff exhausted/)).toBeTruthy());
  expect(screen.getByText(/Unavailable · anchor data/)).toBeTruthy();
  expect(
    screen.getByText(/BUY 2 · 83,788.60 · Moderately strong \(中等偏强\)/),
  ).toBeTruthy();
  expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
  // Auto refresh: non-fresh timeframes except the page's own 5m; the fresh, complete 1h is left alone.
  await waitFor(() => {
    const posted = fetchMock.mock.calls
      .filter(([url]) => String(url).endsWith("/jobs"))
      .map(([, init]) => JSON.parse(String((init as RequestInit).body)).stream.timeframe);
    expect(posted.sort()).toEqual(["15m", "1d", "4h"]);
  });
  // Option board uses the swing regime, which is unavailable in the sample.
  fireEvent.click(screen.getByRole("radio", { name: "Option strangle (期权双卖)" }));
  expect(
    screen.getByText(/BUY 2 · 83,788.60 · Moderate \(中等\) · base level · regime unavailable/),
  ).toBeTruthy();
});

it("also refreshes a fresh timeframe whose history is incomplete", async () => {
  const incompleteHour = {
    ...sampleContext,
    timeframes: sampleContext.timeframes.map((tf) =>
      tf.timeframe === "1h" ? { ...tf, history_complete: false } : tf,
    ),
  };
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) =>
    url.includes("/market-context")
      ? new Response(JSON.stringify(incompleteHour))
      : new Response(JSON.stringify({}), { status: 500 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RegimeCheck stream={stream} rules={rules} />
    </QueryClientProvider>,
  );
  // 1h is fresh but incomplete, so it is due for refresh alongside the other non-fresh
  // timeframes; only the page's own 5m is skipped.
  await waitFor(() => {
    const posted = fetchMock.mock.calls
      .filter(([url]) => String(url).endsWith("/jobs"))
      .map(([, init]) => JSON.parse(String((init as RequestInit).body)).stream.timeframe);
    expect(posted.sort()).toEqual(["15m", "1d", "1h", "4h"]);
  });
});

it("has an i18n entry for every dynamic key the component can build", () => {
  const dynamicKeys = [
    ...["decay", "rev", "pump", "none", "unavailable"].map((v) => `regime.value.${v}`),
    ...["fresh", "delayed", "stale", "unavailable", "simulated"].map(
      (v) => `regime.status.${v}`,
    ),
    ...["up", "down"].map((v) => `regime.trend.${v}`),
    ...[1, 2, 3, 4, 5].map((n) => `regime.level.${n}`),
    ...["cta", "opt", "all"].map((v) => `regime.board.${v}`),
    ...["intraday", "swing"].map((v) => `regime.calibrate.${v}`),
    ...["intraday", "swing"].map((v) => `regime.${v}`),
    ...["stale", "unavailable"].map((v) => `regime.reason.${v}`),
    ...["up", "down"].map((v) => `regime.s9.${v}`),
  ];
  for (const key of dynamicKeys) {
    expect(messages.en).toHaveProperty(key);
  }
});

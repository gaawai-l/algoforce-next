import { renderHook, waitFor, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useInitialMarketRefresh } from "./use-initial-market-refresh";
afterEach(cleanup);
it("loads each missing stream once without retrying on repeated workspace polls", async () => {
  const refresh = vi.fn().mockResolvedValue(undefined);
  const view = renderHook(
    ({ scope, enabled }) => useInitialMarketRefresh(scope, enabled, refresh),
    { initialProps: { scope: "binance:BTC:5m", enabled: false } },
  );
  expect(refresh).not.toHaveBeenCalled();
  view.rerender({ scope: "binance:BTC:5m", enabled: true });
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  view.rerender({ scope: "binance:BTC:5m", enabled: true });
  expect(refresh).toHaveBeenCalledTimes(1);
  view.rerender({ scope: "binance:BTC:15m", enabled: true });
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
  view.rerender({ scope: "binance:BTC:5m", enabled: true });
  expect(refresh).toHaveBeenCalledTimes(2);
});

it("refreshes after each close while open, not on every poll or historical replay", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-28T00:14:59Z"));
  try {
    const { act } = await import("@testing-library/react");
    const { useCloseBoundaryRefresh } =
      await import("./use-initial-market-refresh");
    const refresh = vi.fn().mockResolvedValue(undefined);
    const view = renderHook(
      ({ enabled, nextClose }) =>
        useCloseBoundaryRefresh("btc:15m", enabled, nextClose, refresh),
      {
        initialProps: { enabled: true, nextClose: "2026-09-28T00:15:00Z" },
      },
    );
    await act(() => vi.advanceTimersByTimeAsync(2999));
    expect(refresh).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(refresh).toHaveBeenCalledTimes(1);
    view.rerender({ enabled: true, nextClose: "2026-09-28T00:15:00Z" });
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect(refresh).toHaveBeenCalledTimes(1);
    view.rerender({ enabled: true, nextClose: "2026-09-28T00:30:00Z" });
    await act(() => vi.advanceTimersByTimeAsync(900000));
    expect(refresh).toHaveBeenCalledTimes(2);
    view.rerender({ enabled: false, nextClose: "2026-09-28T00:45:00Z" });
    await act(() => vi.advanceTimersByTimeAsync(900000));
    expect(refresh).toHaveBeenCalledTimes(2);
  } finally {
    vi.useRealTimers();
  }
});

it("waits while hidden and catches up once on return without background scheduling", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-28T01:00:05Z"));
  const visibility = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("hidden");
  try {
    const { act } = await import("@testing-library/react");
    const { useCloseBoundaryRefresh } =
      await import("./use-initial-market-refresh");
    const refresh = vi.fn().mockResolvedValue(undefined);
    const view = renderHook(() =>
      useCloseBoundaryRefresh("btc:15m", true, "2026-09-28T01:00:00Z", refresh),
    );
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(refresh).not.toHaveBeenCalled();
    visibility.mockReturnValue("visible");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
    view.unmount();
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(900000);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  } finally {
    visibility.mockRestore();
    vi.useRealTimers();
  }
});

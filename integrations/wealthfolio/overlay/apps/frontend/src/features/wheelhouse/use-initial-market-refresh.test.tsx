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

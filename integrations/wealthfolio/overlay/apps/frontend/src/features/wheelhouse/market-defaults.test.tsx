import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import MarketPage from "./market-page";
const mocks = vi.hoisted(() => ({ workspace: vi.fn(), submit: vi.fn() }));
vi.mock("./market-chart", () => ({ MarketChart: () => null }));
vi.mock("./demark-details", () => ({ DemarkDetails: () => null }));
vi.mock("./regime-check", () => ({ RegimeCheck: () => null }));
vi.mock("./language-toggle", () => ({ LanguageToggle: () => null }));
vi.mock("./i18n", () => ({
  useWheelhouseText: () => ({ text: (key: string) => key }),
  labeled: (_: unknown, _kind: string, value: string) => value,
  issueText: () => "",
}));
vi.mock("./client", async (original) => ({
  ...(await original<typeof import("./client")>()),
  getServiceStatus: async () => ({ service_version: "test" }),
  getWorkspace: mocks.workspace,
  getSnapshots: async () => [],
  getJobEvents: async () => [],
  submitJob: mocks.submit,
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it.each([
  ["BTCUSDT", "bybit", "bybit-spot", "BTC"],
  ["ETHUSDT", "binance", "binance-usdm-perpetual", "ETH"],
  ["MUUSDT", "binance", "binance-usdm-perpetual", "MU"],
])(
  "routes %s to its assigned market even with a legacy fixture URL",
  async (symbol, source, venue, currency) => {
    mocks.workspace.mockResolvedValue({
      snapshot: null,
      latest_job: null,
      refresh_job: null,
      schedule: null,
      current_state: "unavailable",
    });
    mocks.submit.mockImplementation(() => new Promise(() => {}));
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter
          initialEntries={[
            `/market-intelligence?source=fixture&symbol=${symbol}`,
          ]}
        >
          <MarketPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    expect(mocks.submit.mock.calls[0][0].stream).toMatchObject({
      source,
      symbol,
      venue,
      base_currency: currency,
    });
    expect(
      screen
        .getByRole("tab", { name: /method\.td/ })
        .getAttribute("aria-selected"),
    ).toBe("true");
    expect(screen.queryByLabelText("field.source")).toBeNull();
    expect(screen.queryByRole("button", { name: "action.refresh" })).toBeNull();
    expect(screen.queryByRole("button", { name: "chart.load" })).toBeNull();
  },
);

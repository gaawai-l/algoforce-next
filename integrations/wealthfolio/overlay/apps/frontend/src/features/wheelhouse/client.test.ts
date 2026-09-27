import { afterEach, describe, expect, it, vi } from "vitest";
import { getServiceStatus } from "./client";

const validResponse = {
  service: "wheelhouse-python",
  status: "ready",
  contract_version: "1",
  service_version: "0.1.0",
  python_version: "3.14.6",
  checked_at: "2026-09-26T00:00:00Z",
  read_only: true,
  integrations: {
    broker: "not_connected",
    market_data: "not_connected",
    analytics: "baseline_ready",
  },
  capabilities: ["service_status"],
};

afterEach(() => vi.unstubAllGlobals());

describe("Wealthfolio → Python contract", () => {
  it("accepts a compatible response without claiming market or broker integration", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(validResponse))),
    );
    const status = await getServiceStatus();
    expect(status.read_only).toBe(true);
    expect(status.integrations.broker).toBe("not_connected");
  });

  it("rejects a responding service with an incompatible contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ ...validResponse, contract_version: "2" }),
          ),
        ),
    );
    await expect(getServiceStatus()).rejects.toThrow("incompatible");
  });

  it("surfaces proxy failures rather than showing connected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("Unavailable", { status: 502 })),
    );
    await expect(getServiceStatus()).rejects.toThrow("HTTP 502");
  });
});

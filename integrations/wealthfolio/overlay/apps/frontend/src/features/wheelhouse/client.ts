import { z } from "zod";
import type { components } from "./api-schema";

export type ServiceStatus = components["schemas"]["ServiceStatus"];

const statusSchema: z.ZodType<ServiceStatus> = z.object({
  service: z.literal("wheelhouse-python"),
  status: z.literal("ready"),
  contract_version: z.literal("1"),
  service_version: z.string(),
  python_version: z.string(),
  checked_at: z.string().datetime(),
  read_only: z.literal(true),
  integrations: z.object({
    broker: z.literal("not_connected"),
    market_data: z.literal("not_connected"),
    analytics: z.literal("not_implemented"),
  }),
  capabilities: z.array(z.literal("service_status")),
});

export async function getServiceStatus(
  signal?: AbortSignal,
): Promise<ServiceStatus> {
  const timeout = AbortSignal.timeout(5000);
  const response = await fetch("/api/wheelhouse/v1/status", {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(
      `Python service unavailable (HTTP ${response.status}). Start the local workspace and retry.`,
    );
  }
  const parsed = statusSchema.safeParse(await response.json());
  if (!parsed.success) {
    throw new Error(
      "Python service contract is incompatible. Update the host and service together.",
    );
  }
  return parsed.data;
}

import { useQuery } from "@tanstack/react-query";
import { Badge, Button, Page, PageContent, PageHeader } from "@wealthfolio/ui";
import { getServiceStatus } from "./client";

export default function MarketPage() {
  const status = useQuery({
    queryKey: ["wheelhouse", "service-status", "v1"],
    queryFn: ({ signal }) => getServiceStatus(signal),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: true,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  });
  const connected = status.isSuccess && !status.isFetching;

  return (
    <Page>
      <PageHeader
        heading="Market intelligence"
        text="Wheelhouse · Local analysis foundation"
      />
      <PageContent>
        <section
          className="max-w-4xl space-y-8 pb-12"
          aria-label="Analysis foundation"
        >
          <div className="flex flex-wrap items-center justify-between gap-4 border-b pb-6">
            <div>
              <Badge variant="outline">Architecture preview</Badge>
              <h2 className="mt-4 text-xl font-semibold">
                Python analysis connection
              </h2>
              <p className="text-muted-foreground mt-2 text-sm">
                This workspace uses Wealthfolio for portfolio management and a
                separate local Python process for analysis.
              </p>
            </div>
            <Button
              variant="outline"
              disabled={status.isFetching}
              onClick={() => void status.refetch()}
            >
              {status.isFetching ? "Checking…" : "Check connection"}
            </Button>
          </div>
          <div role="status" aria-live="polite" className="space-y-3">
            <h3 className="font-medium">
              {status.isFetching
                ? "Checking Python service…"
                : connected
                  ? "Python service connected"
                  : "Python service unavailable"}
            </h3>
            {status.isError && (
              <p role="alert" className="text-destructive text-sm">
                {status.error.message}
              </p>
            )}
            {connected && status.data && (
              <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-muted-foreground">Service version</dt>
                  <dd className="font-mono">{status.data.service_version}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Python version</dt>
                  <dd className="font-mono">{status.data.python_version}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Contract</dt>
                  <dd className="font-mono">
                    v{status.data.contract_version} · Read-only
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Last verified</dt>
                  <dd className="font-mono break-words">
                    {status.data.checked_at}
                  </dd>
                </div>
              </dl>
            )}
          </div>
          <div className="space-y-3 border-t pt-6">
            <h3 className="font-medium">Integration readiness</h3>
            <dl className="space-y-3 text-sm">
              <div className="flex flex-wrap justify-between gap-2">
                <dt>Wealthfolio host</dt>
                <dd>3.8.0 · Local development</dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <dt>Market data</dt>
                <dd className="text-muted-foreground">Not connected</dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <dt>moomoo account</dt>
                <dd className="text-muted-foreground">Not connected</dd>
              </div>
              <div className="flex flex-wrap justify-between gap-2">
                <dt>Strategy engine</dt>
                <dd className="text-muted-foreground">
                  Not implemented in this foundation
                </dd>
              </div>
            </dl>
            <p className="text-muted-foreground pt-3 text-sm">
              No market signals or account recommendations are generated. The
              earlier simulated dashboard remains a separate design reference.
            </p>
          </div>
        </section>
      </PageContent>
    </Page>
  );
}

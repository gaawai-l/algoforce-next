import { useEffect, useRef } from "react";

/** Load a missing result once per selected stream, without a retry loop. */
export function useInitialMarketRefresh(
  scope: string,
  enabled: boolean,
  refresh: () => Promise<void>,
) {
  const attempted = useRef(new Set<string>());
  useEffect(() => {
    if (!enabled || attempted.current.has(scope)) return;
    attempted.current.add(scope);
    void refresh();
  }, [scope, enabled, refresh]);
}

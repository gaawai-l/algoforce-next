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

/** Refresh only the visible live view, once after each expected candle close. */
export function useCloseBoundaryRefresh(
  scope: string,
  enabled: boolean,
  nextClose: string | null | undefined,
  refresh: () => Promise<void>,
) {
  const attempted = useRef(new Map<string, number>());
  useEffect(() => {
    if (!enabled || !nextClose) return;
    const boundary = Date.parse(nextClose);
    if (!Number.isFinite(boundary) || attempted.current.get(scope) === boundary)
      return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      if (timer !== undefined) clearTimeout(timer);
      if (
        document.visibilityState === "hidden" ||
        attempted.current.get(scope) === boundary
      )
        return;
      const delay = Math.max(0, boundary + 2000 - Date.now());
      timer = setTimeout(
        () => {
          if (document.visibilityState === "hidden") return;
          attempted.current.set(scope, boundary);
          void refresh();
        },
        Math.min(delay, 2147483647),
      );
    };
    arm();
    document.addEventListener("visibilitychange", arm);
    return () => {
      if (timer !== undefined) clearTimeout(timer);
      document.removeEventListener("visibilitychange", arm);
    };
  }, [scope, enabled, nextClose, refresh]);
}

/** Refresh the visible live view and recover failures without creating a retry storm. */
export function useLiveMarketRefresh(
  scope: string,
  enabled: boolean,
  refresh: () => Promise<void>,
) {
  const latest = useRef(refresh);
  latest.current = refresh;
  const attempted = useRef(new Map<string, number>());
  useEffect(() => {
    if (!enabled) return;
    const run = () => {
      if (document.visibilityState === "hidden") return;
      const now = Date.now();
      const previous = attempted.current.get(scope);
      if (previous !== undefined && now - previous < 60_000) return;
      attempted.current.set(scope, now);
      void latest.current().catch(() => {
        /* The page displays the acquisition error. */
      });
    };
    run();
    const timer = setInterval(run, 5000);
    document.addEventListener("visibilitychange", run);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", run);
    };
  }, [scope, enabled]);
}

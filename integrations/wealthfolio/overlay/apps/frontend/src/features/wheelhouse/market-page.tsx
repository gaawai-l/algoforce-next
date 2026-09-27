import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Page, PageContent, PageHeader } from "@wealthfolio/ui";
import { useSearchParams } from "react-router-dom";
import { MarketChart } from "./market-chart";
import { useInitialMarketRefresh } from "./use-initial-market-refresh";
import { DemarkDetails } from "./demark-details";
import { defaultDemarkConfig } from "./demark-contract";
import {
  PREFIX,
  getServiceStatus,
  getWorkspace,
  getSnapshots,
  getSnapshot,
  getJob,
  getJobEvents,
  submitJob,
  updateSchedule,
  money,
  stamp,
  type JobRequest,
  type Stream,
  type Rules,
} from "./client";
import "./market.css";

const methods = [
  { id: "td", name: "TD Sequential" },
  { id: "levels", name: "Key levels" },
  { id: "fib", name: "Fibonacci" },
] as const;
type Method = (typeof methods)[number]["id"];
const timeframes: Stream["timeframe"][] = ["5m", "15m", "1h", "4h", "1d"];
const activeStates = new Set(["queued", "running", "retry_wait"]);

function Facts({ entries }: { entries: [string, string][] }) {
  return (
    <dl className="wh-facts">
      {entries.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function MarketPage() {
  const cache = useQueryClient();
  const [search, setSearch] = useSearchParams();
  const updateQuery = (name: string, value: string | null) => {
    const next = new URLSearchParams(window.location.search);
    if (value === null) next.delete(name);
    else next.set(name, value);
    if (["source", "symbol", "timeframe"].includes(name))
      next.delete("snapshot");
    if (
      next.toString() !== new URLSearchParams(window.location.search).toString()
    )
      setSearch(next, { replace: true });
  };
  const source: Stream["source"] =
    search.get("source") === "fixture" ? "fixture" : "binance";
  const symbol: Stream["symbol"] =
    search.get("symbol") === "ETHUSDT" ? "ETHUSDT" : "BTCUSDT";
  const timeframe: Stream["timeframe"] =
    timeframes.find((tf) => tf === search.get("timeframe")) ?? "1h";
  const method: Method =
    methods.find((item) => item.id === search.get("method"))?.id ?? "levels";
  const setSource = (value: Stream["source"]) => updateQuery("source", value);
  const setSymbol = (value: Stream["symbol"]) => updateQuery("symbol", value);
  const setTimeframe = (value: Stream["timeframe"]) =>
    updateQuery("timeframe", value);
  const setMethod = (value: Method) => updateQuery("method", value);
  const initialWindow = Number(search.get("window") ?? 20);
  const [windowSize, setWindowSize] = useState(
    Number.isInteger(initialWindow) &&
      initialWindow >= 2 &&
      initialWindow <= 200
      ? initialWindow
      : 20,
  );
  const [visibleBars, setVisibleBars] = useState(100);
  const [sequenceId, setSequenceId] = useState<string | null>(null);
  const selectedId = /^[a-f0-9]{64}$/.test(search.get("snapshot") ?? "")
    ? search.get("snapshot")
    : null;
  const setSelectedId = (value: string | null) =>
    updateQuery("snapshot", value);
  const [pending, setPending] = useState<{
    id: string;
    kind: "refresh" | "analyze";
  } | null>(null);
  const [marketCutoff, setMarketCutoff] = useState("");
  const [cutoffEdited, setCutoffEdited] = useState(false);
  const [knowledgeMode, setKnowledgeMode] = useState("pinned");
  const [actionError, setActionError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const selection = useRef(0);
  const previousScope = useRef(`${source}:${symbol}:${timeframe}`);
  const stream = useMemo<Stream>(
    () => ({
      source,
      symbol,
      timeframe,
      venue: "binance-spot",
      market_session: "24/7",
      timezone: "UTC",
      quote_currency: "USDT",
      base_currency: symbol === "BTCUSDT" ? "BTC" : "ETH",
      price_encoding: "decimal_string_18_places",
    }),
    [source, symbol, timeframe],
  );
  const rules: Rules = {
    engine_version: "baseline-v1",
    window: windowSize,
    demark: defaultDemarkConfig,
  };
  const status = useQuery({
    queryKey: ["wheelhouse", "service-status", "v1"],
    queryFn: ({ signal }) => getServiceStatus(signal),
    retry: false,
    refetchInterval: 10000,
    refetchOnWindowFocus: true,
  });
  const workspace = useQuery({
    queryKey: ["wh", "workspace", stream],
    queryFn: ({ signal }) => getWorkspace(stream, signal),
    retry: false,
    refetchInterval: 2000,
  });
  const history = useQuery({
    queryKey: ["wh", "snapshots", stream],
    queryFn: ({ signal }) => getSnapshots(stream, signal),
    retry: false,
    refetchInterval: 10000,
  });
  const saved = useQuery({
    queryKey: ["wh", "snapshot", selectedId],
    queryFn: ({ signal }) => getSnapshot(selectedId!, signal),
    enabled: !!selectedId,
    retry: false,
  });
  const task = useQuery({
    queryKey: ["wh", "job", pending?.id],
    queryFn: ({ signal }) => getJob(pending!.id, signal),
    enabled: !!pending,
    retry: false,
    refetchInterval: (q) =>
      q.state.data && !activeStates.has(q.state.data.state) ? false : 500,
  });
  const eventJobId = pending?.id ?? workspace.data?.latest_job?.job_id;
  const events = useQuery({
    queryKey: ["wh", "events", eventJobId],
    queryFn: ({ signal }) => getJobEvents(eventJobId!, signal),
    enabled: !!eventJobId,
    retry: false,
    refetchInterval: pending ? 1000 : false,
  });
  const schedule = useMutation({
    mutationFn: (enabled: boolean) => updateSchedule(stream, rules, enabled),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["wh", "workspace"] });
    },
    onError: (error: Error) => setActionError(error.message),
  });
  const candidate = selectedId ? saved.data : workspace.data?.snapshot;
  const analysis =
    candidate?.stream.source === source &&
    candidate.stream.symbol === symbol &&
    candidate.stream.timeframe === timeframe
      ? candidate
      : undefined;
  const offline = status.isError || workspace.isError;
  const busy = !!pending || schedule.isPending || submitting;
  const latestJob = task.data ?? workspace.data?.latest_job;
  const frameState = offline
    ? "offline cache"
    : selectedId
      ? "saved snapshot"
      : (workspace.data?.current_state ?? "unavailable");

  useEffect(() => {
    const scope = `${source}:${symbol}:${timeframe}`;
    if (previousScope.current === scope) return;
    previousScope.current = scope;
    selection.current += 1;
    setSelectedId(null);
    setPending(null);
    setActionError("");
    setMarketCutoff("");
    setCutoffEdited(false);
  }, [source, symbol, timeframe]);
  useEffect(() => {
    if (!cutoffEdited && analysis?.closed_bar_time)
      setMarketCutoff(
        new Date(analysis.closed_bar_time).toISOString().slice(0, 19),
      );
  }, [analysis?.snapshot_id, analysis?.closed_bar_time, cutoffEdited]);
  useEffect(() => {
    if (!pending || !task.data || activeStates.has(task.data.state)) return;
    if (task.data.state === "succeeded") {
      if (pending.kind === "analyze") setSelectedId(task.data.snapshot_id);
      else setSelectedId(null);
    } else
      setActionError(
        `Task failed: ${task.data.error_code ?? "unknown error"}. Existing snapshots were preserved.`,
      );
    setPending(null);
    void cache.invalidateQueries({ queryKey: ["wh"] });
  }, [pending, task.data, cache]);

  const start = async (kind: "refresh" | "analyze") => {
    setActionError("");
    if (!Number.isInteger(windowSize) || windowSize < 2 || windowSize > 200) {
      setActionError("Window must be an integer from 2 to 200.");
      return;
    }
    const token = selection.current;
    const request: JobRequest = { kind, stream, rules };
    if (kind === "analyze") {
      if (!analysis || !marketCutoff) return;
      const entered = marketCutoff.replace(/Z$/, "");
      const normalized = entered.length === 16 ? entered + ":00" : entered;
      const parsedCutoff = new Date(normalized + "Z");
      if (
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(normalized) ||
        !Number.isFinite(parsedCutoff.getTime()) ||
        parsedCutoff.toISOString().slice(0, 19) !== normalized
      ) {
        setActionError(
          "Enter a valid UTC cutoff, for example 2026-09-25T12:00:00.",
        );
        return;
      }
      const cutoff = parsedCutoff.toISOString();
      request.market_at = cutoff;
      request.knowledge_at =
        knowledgeMode === "pinned" ? analysis.knowledge_at : cutoff;
    }
    setSubmitting(true);
    try {
      const job = await submitJob(request, crypto.randomUUID());
      if (token === selection.current) setPending({ id: job.job_id, kind });
    } catch (error) {
      if (token === selection.current) setActionError((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  };
  useInitialMarketRefresh(
    `${source}:${symbol}:${timeframe}`,
    !selectedId &&
      workspace.isSuccess &&
      !!status.data &&
      !offline &&
      !busy &&
      !actionError &&
      !workspace.data?.refresh_job?.error_code &&
      !activeStates.has(workspace.data?.latest_job?.state ?? "") &&
      (!analysis?.bars.length ||
        !analysis.demark ||
        workspace.data?.current_state === "stale"),
    () => start("refresh"),
  );
  const methodKey = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % methods.length;
    else if (event.key === "ArrowLeft")
      next = (index + methods.length - 1) % methods.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = methods.length - 1;
    else return;
    event.preventDefault();
    setMethod(methods[next].id);
    document.getElementById(`wh-tab-${methods[next].id}`)?.focus();
  };
  const latestPoint = analysis?.points.at(-1);
  const tdSequences = [...(analysis?.demark?.sequences ?? [])].reverse();
  const selectedSequence =
    tdSequences.find((s) => s.sequence_id === sequenceId) ??
    tdSequences.find(
      (s) =>
        s.continuity === "observed" &&
        (s.setup_status === "forming" ||
          ["active", "count13_unqualified"].includes(s.countdown_status) ||
          s.risk_status === "valid"),
    ) ??
    tdSequences[0];
  return (
    <Page>
      <PageHeader
        heading="Market intelligence"
        text="Wheelhouse · Traceable market analysis"
      />
      <PageContent>
        <div className="wh-market">
          <div className="wh-service">
            <span className={`wh-dot ${offline ? "wh-down" : ""}`} />
            <span>
              {offline
                ? "Python service unavailable"
                : status.data
                  ? "Python service connected"
                  : "Connecting to Python…"}
            </span>
            <span className="wh-muted">
              Local / read-only / {status.data?.service_version ?? "—"}
            </span>
          </div>
          <div className="wh-toolbar">
            <label>
              Market / symbol
              <select
                aria-label="Market / symbol"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value as Stream["symbol"])}
              >
                <option value="BTCUSDT">Crypto · BTC / USDT</option>
                <option value="ETHUSDT">Crypto · ETH / USDT</option>
              </select>
            </label>
            <label>
              Data source
              <select
                value={source}
                onChange={(e) => setSource(e.target.value as Stream["source"])}
              >
                <option value="fixture">Synthetic fixture</option>
                <option value="binance">Binance public spot</option>
              </select>
            </label>
            <label className="wh-window">
              Rule window
              <input
                aria-label="Rule window"
                type="number"
                min="2"
                max="200"
                value={windowSize}
                onChange={(e) => {
                  setWindowSize(Number(e.target.value));
                  updateQuery("window", e.target.value);
                }}
              />
            </label>
            <button
              className="wh-primary"
              disabled={busy || offline}
              onClick={() => void start("refresh")}
            >
              {pending?.kind === "refresh"
                ? "Refreshing…"
                : "Refresh market data"}
            </button>
            <div className="wh-price">
              <span>LAST CLOSED PRICE</span>
              <strong>
                {money(analysis?.bars.at(-1)?.bar.close)} <small>USDT</small>
              </strong>
            </div>
          </div>
          <div className="wh-meta">
            <span
              className={`wh-badge ${source === "fixture" ? "wh-amber" : ""}`}
            >
              {source === "fixture" ? "SIMULATED" : "PUBLIC SPOT"}
            </span>
            <span className="wh-badge">{frameState.toUpperCase()}</span>
            <label className="wh-inline">
              <input
                type="checkbox"
                checked={workspace.data?.schedule?.request.enabled ?? false}
                disabled={schedule.isPending || offline}
                onChange={(e) => schedule.mutate(e.target.checked)}
              />{" "}
              Refresh after each close
            </label>
            {workspace.data?.schedule?.request.enabled && (
              <small>Next {stamp(workspace.data.schedule.next_due)}</small>
            )}
          </div>
          {(offline ||
            actionError ||
            saved.isError ||
            workspace.data?.refresh_job?.error_code) && (
            <div className="wh-alert" role="alert">
              {offline
                ? "Analysis service unavailable. Any displayed chart is a saved result, not a live update."
                : actionError ||
                  (saved.isError ? saved.error.message : "") ||
                  `Last refresh: ${workspace.data?.refresh_job?.error_code}. Saved results are preserved; no fallback source is used.`}
            </div>
          )}
          {latestJob && (
            <div className="wh-task" role="status">
              <span>
                Task {latestJob.state.replaceAll("_", " ")} · attempt{" "}
                {latestJob.attempts}/3
              </span>
              <span>
                {latestJob.request.kind === "analyze"
                  ? "Using stored revisions"
                  : latestJob.checkpoint_batch_id
                    ? "Data checkpoint saved"
                    : "Awaiting data checkpoint"}
              </span>
              {latestJob.state === "retry_wait" && (
                <span>Retry {stamp(latestJob.next_attempt_at)}</span>
              )}
            </div>
          )}
          <div
            className="wh-methods"
            role="tablist"
            aria-label="Market analysis method"
          >
            {methods.map((item, i) => (
              <button
                key={item.id}
                id={`wh-tab-${item.id}`}
                role="tab"
                aria-selected={method === item.id}
                aria-controls={`wh-panel-${item.id}`}
                tabIndex={method === item.id ? 0 : -1}
                onClick={() => setMethod(item.id)}
                onKeyDown={(event) => methodKey(event, i)}
              >
                <small>0{i + 1}</small>
                {item.name}
              </button>
            ))}
          </div>
          <div className="wh-framebar">
            <div role="group" aria-label="Timeframe">
              {timeframes.map((tf) => (
                <button
                  key={tf}
                  aria-pressed={tf === timeframe}
                  onClick={() => setTimeframe(tf)}
                >
                  {tf.toUpperCase()}
                </button>
              ))}
            </div>
            <label className="wh-inline">
              Visible bars
              <select
                value={visibleBars}
                onChange={(e) => setVisibleBars(Number(e.target.value))}
              >
                <option value="50">50</option>
                <option value="100">100</option>
                <option value="200">200</option>
              </select>
            </label>
            <span className="wh-muted">
              24/7 · UTC · {selectedId ? "REPLAY" : "LATEST CAPTURE"}
            </span>
          </div>
          <section
            className="wh-analysis"
            id={`wh-panel-${method}`}
            role="tabpanel"
            aria-labelledby={`wh-tab-${method}`}
          >
            <div className="wh-chart-area">
              <div className="wh-chart-title">
                <h2>{symbol.replace("USDT", " / USDT")}</h2>
                <span>
                  {timeframe.toUpperCase()} · {analysis?.bars.length ?? 0}{" "}
                  closed bars
                </span>
              </div>
              {analysis ? (
                <MarketChart
                  analysis={analysis}
                  visibleBars={visibleBars}
                  showLevels={method === "levels"}
                  showDemark={method === "td"}
                  sequence={selectedSequence}
                />
              ) : (
                <div className="wh-empty">
                  <p>
                    {workspace.isLoading || saved.isFetching
                      ? "Loading saved market data…"
                      : pending?.kind === "refresh" ||
                          submitting ||
                          activeStates.has(latestJob?.state ?? "")
                        ? `Fetching ${timeframe.toUpperCase()} bars and calculating Sequential…`
                        : `No saved ${timeframe.toUpperCase()} dataset for this source.`}
                  </p>
                  <button
                    disabled={busy || offline}
                    onClick={() => void start("refresh")}
                  >
                    {busy ? "Loading market data…" : "Load this timeframe"}
                  </button>
                </div>
              )}
              {analysis && (
                <div className="wh-provenance">
                  <div>
                    <span>LAST CLOSED BAR</span>
                    <strong>{stamp(analysis.closed_bar_time)}</strong>
                  </div>
                  <div>
                    <span>FORMING BAR · EXCLUDED</span>
                    <strong>{stamp(analysis.forming_bar_time)}</strong>
                  </div>
                  <div>
                    <span>DATA ACQUIRED</span>
                    <strong>{stamp(analysis.fetched_at)}</strong>
                  </div>
                  <div>
                    <span>NEXT EXPECTED CLOSE</span>
                    <strong>{stamp(analysis.expected_next_close)}</strong>
                  </div>
                </div>
              )}
            </div>
            <aside className="wh-inspector" aria-label="Method details">
              <span className="wh-eyebrow">METHOD INSPECTOR</span>
              <h2>
                {method === "levels"
                  ? "Rolling structure"
                  : method === "td"
                    ? "DeMark engine"
                    : "Fibonacci anchors"}
              </h2>
              {method === "levels" ? (
                <>
                  <p>
                    Server-calculated prior-window boundaries and a simple
                    moving average validate the shared analysis pipeline.
                  </p>
                  <Facts
                    entries={[
                      [
                        `SMA ${analysis?.rules.window ?? windowSize}`,
                        money(latestPoint?.sma),
                      ],
                      ["Prior-window high", money(latestPoint?.prior_high)],
                      ["Prior-window low", money(latestPoint?.prior_low)],
                      [
                        "Warm-up",
                        analysis
                          ? `${analysis.warmup_complete ? "Complete" : "Incomplete"} / ${analysis.warmup_required} bars`
                          : "No dataset",
                      ],
                      [
                        "Calculation",
                        analysis?.rules.engine_version ?? "baseline-v1",
                      ],
                      ["Trading signal", "Not implemented"],
                    ]}
                  />
                  <p className="wh-muted">
                    Current bar excluded from high/low boundaries. These
                    references are not validated S/R clusters or reversal
                    signals.
                  </p>
                </>
              ) : method === "td" ? (
                <DemarkDetails
                  result={analysis?.demark}
                  selectedId={selectedSequence?.sequence_id ?? null}
                  onSelect={setSequenceId}
                />
              ) : (
                <>
                  <span className="wh-badge wh-amber">NOT YET INTEGRATED</span>
                  <p>
                    User-selected anchors will be integrated as a separate
                    calculation module. No automatic anchors or implied
                    confluence are shown.
                  </p>
                </>
              )}
              {analysis && (
                <>
                  <h3>Data quality</h3>
                  {analysis.issues.length ? (
                    <ul>
                      {analysis.issues.map((issue) => (
                        <li key={issue}>{issue}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>No missing intervals in the selected dataset.</p>
                  )}
                  <p className="wh-muted">
                    {analysis.stream.source} / {analysis.stream.venue}
                    <br />
                    {analysis.stream.quote_currency} ·{" "}
                    {analysis.stream.market_session} ·{" "}
                    {analysis.stream.timezone}
                  </p>
                </>
              )}
            </aside>
          </section>
          <section className="wh-replay">
            <div className="wh-section-title">
              <div>
                <span className="wh-eyebrow">REPRODUCIBLE BY DESIGN</span>
                <h2>Snapshots & replay</h2>
              </div>
              {analysis && (
                <a
                  href={`${PREFIX}/snapshots/${analysis.snapshot_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Snapshot JSON ↗
                </a>
              )}
            </div>
            <label>
              Saved analysis
              <select
                aria-label="Saved analysis"
                value={selectedId ?? ""}
                onChange={(e) => {
                  setSelectedId(e.target.value || null);
                  setMarketCutoff("");
                  setCutoffEdited(false);
                }}
              >
                <option value="">Latest captured analysis</option>
                {history.data?.map((item) => (
                  <option key={item.snapshot_id} value={item.snapshot_id}>
                    {stamp(item.market_at)} · window {item.rules.window} ·{" "}
                    {item.bar_count} bars ·{" "}
                    {item.rules.demark ? "Sequential" : "Baseline"} ·{" "}
                    {item.data_state}
                  </option>
                ))}
              </select>
            </label>
            {analysis && (
              <>
                <div className="wh-cutoffs">
                  <label>
                    Market cutoff (UTC)
                    <input
                      type="text"
                      placeholder="YYYY-MM-DDTHH:mm:ss"
                      value={marketCutoff}
                      onChange={(e) => {
                        setMarketCutoff(e.target.value);
                        setCutoffEdited(true);
                      }}
                    />
                  </label>
                  <label>
                    Data knowledge
                    <select
                      value={knowledgeMode}
                      onChange={(e) => setKnowledgeMode(e.target.value)}
                    >
                      <option value="pinned">
                        Pinned dataset revision · retrospective
                      </option>
                      <option value="as_known">
                        Only data known at market cutoff
                      </option>
                    </select>
                  </label>
                  <button
                    disabled={busy || offline || !marketCutoff}
                    onClick={() => void start("analyze")}
                  >
                    {pending?.kind === "analyze"
                      ? "Replaying…"
                      : "Run historical replay"}
                  </button>
                </div>
                <p className="wh-muted">
                  Pinned knowledge cutoff: {stamp(analysis.knowledge_at)}.
                  Historical bars downloaded later are not presented as data
                  known in the past.
                </p>
                <p className="wh-hash">
                  Input fingerprint {analysis.input_hash.slice(0, 24)} ·{" "}
                  {analysis.mode.replaceAll("_", " ")} ·{" "}
                  {analysis.rules.engine_version}
                </p>
              </>
            )}
          </section>
          <details className="wh-disclosure">
            <summary>Task audit & checkpoint</summary>
            {events.data && (
              <div className="wh-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Time (UTC)</th>
                      <th>State</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.data.map((event, i) => (
                      <tr key={i}>
                        <td>{stamp(event.at)}</td>
                        <td>{event.state}</td>
                        <td>{event.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {latestJob?.checkpoint_batch_id && (
              <a
                href={`${PREFIX}/batches/${latestJob.checkpoint_batch_id}`}
                target="_blank"
                rel="noreferrer"
              >
                Raw captured batch ↗
              </a>
            )}
          </details>
          {analysis && (
            <details className="wh-disclosure">
              <summary>Accessible OHLC data & revision IDs</summary>
              <div className="wh-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Open time</th>
                      <th>Open</th>
                      <th>High</th>
                      <th>Low</th>
                      <th>Close</th>
                      <th>Volume</th>
                      <th>Revision</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...analysis.bars].reverse().map((row) => (
                      <tr key={row.revision_id}>
                        <td>{stamp(row.bar.open_time)}</td>
                        <td>{money(row.bar.open)}</td>
                        <td>{money(row.bar.high)}</td>
                        <td>{money(row.bar.low)}</td>
                        <td>{money(row.bar.close)}</td>
                        <td>{money(row.bar.volume)}</td>
                        <td title={row.revision_id}>
                          v{row.revision} · {row.revision_id.slice(0, 8)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
          <footer className="wh-footer">
            Wealthfolio + Python · Local analysis · No brokerage connected · No
            order execution
          </footer>
        </div>
      </PageContent>
    </Page>
  );
}

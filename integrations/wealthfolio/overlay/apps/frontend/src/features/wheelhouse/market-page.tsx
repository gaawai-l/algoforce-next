import { Dropdown, DropdownOption } from "./dropdown";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Page, PageContent, PageHeader } from "@wealthfolio/ui";
import { useSearchParams } from "react-router-dom";
import { LanguageToggle } from "./language-toggle";
import { issueText, labeled, useWheelhouseText } from "./i18n";
import { MarketChart } from "./market-chart";
import { useLiveMarketRefresh } from "./use-initial-market-refresh";
import { DemarkDetails } from "./demark-details";
import { RegimeCheck } from "./regime-check";
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
  money,
  stamp,
  type JobRequest,
  type Stream,
  type Rules,
} from "./client";
import "./market.css";

type Method = "td" | "levels" | "fib";
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
  const { text } = useWheelhouseText();
  const missing = text("missing");
  const methods = [
    { id: "td" as const, name: text("method.td") },
    { id: "levels" as const, name: text("method.levels") },
    { id: "fib" as const, name: text("method.fib") },
  ];
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
  const symbol: Stream["symbol"] =
    search.get("symbol") === "MUUSDT"
      ? "MUUSDT"
      : search.get("symbol") === "ETHUSDT"
        ? "ETHUSDT"
        : "BTCUSDT";
  const source: Stream["source"] = symbol === "BTCUSDT" ? "bybit" : "binance";
  const timeframe: Stream["timeframe"] =
    timeframes.find((tf) => tf === search.get("timeframe")) ?? "1h";
  const method: Method =
    methods.find((item) => item.id === search.get("method"))?.id ?? "td";
  const setSymbol = (value: Stream["symbol"]) => updateQuery("symbol", value);
  const setTimeframe = (value: Stream["timeframe"]) =>
    updateQuery("timeframe", value);
  const setMethod = (value: Method) => updateQuery("method", value);
  useEffect(() => {
    const next = new URLSearchParams(search);
    if (next.get("source") === "fixture") next.delete("snapshot");
    next.delete("source");
    if (!methods.some((item) => item.id === next.get("method")))
      next.set("method", "td");
    if (next.toString() !== search.toString())
      setSearch(next, { replace: true });
  }, [search, setSearch]);
  const initialWindow = Number(search.get("window") ?? 20);
  const [windowSize, setWindowSize] = useState(
    Number.isInteger(initialWindow) &&
      initialWindow >= 2 &&
      initialWindow <= 200
      ? initialWindow
      : 20,
  );
  const [visibleBars, setVisibleBars] = useState(0);
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
      venue: source === "bybit" ? "bybit-spot" : "binance-usdm-perpetual",
      market_session: "24/7",
      timezone: "UTC",
      quote_currency: "USDT",
      base_currency:
        symbol === "BTCUSDT" ? "BTC" : symbol === "ETHUSDT" ? "ETH" : "MU",
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
    staleTime: Infinity,
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
  const candidate = selectedId ? saved.data : workspace.data?.snapshot;
  const analysis =
    candidate?.stream.source === source &&
    candidate.stream.venue === stream.venue &&
    candidate.stream.symbol === symbol &&
    candidate.stream.timeframe === timeframe
      ? candidate
      : undefined;
  const offline = status.isError || workspace.isError;
  const busy = !!pending || submitting;
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
        text("error.taskFailed", {
          code: task.data.error_code ?? text("error.unknown"),
        }),
      );
    setPending(null);
    void cache.invalidateQueries({ queryKey: ["wh"] });
  }, [pending, task.data, cache]);

  const start = async (kind: "refresh" | "analyze") => {
    setActionError("");
    if (!Number.isInteger(windowSize) || windowSize < 2 || windowSize > 200) {
      setActionError(text("error.window"));
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
        setActionError(text("error.cutoff"));
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
  useLiveMarketRefresh(
    `${stream.venue}:${symbol}:${timeframe}`,
    !selectedId &&
      workspace.isSuccess &&
      !!status.data &&
      !offline &&
      !busy &&
      !activeStates.has(workspace.data?.latest_job?.state ?? ""),
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
        heading={text("page.title")}
        text={text("page.subtitle")}
        actions={<LanguageToggle />}
      />
      <PageContent>
        <div className="wh-market">
          <div className="wh-service">
            <span className={`wh-dot ${offline ? "wh-down" : ""}`} />
            <span>
              {offline
                ? text("service.down")
                : status.data
                  ? text("service.up")
                  : text("service.connecting")}
            </span>
            <span className="wh-muted">
              {text("service.local", {
                version: status.data?.service_version ?? "—",
              })}
            </span>
          </div>
          <div className="wh-toolbar">
            <label>
              {text("field.symbol")}
              <Dropdown
                aria-label={text("field.symbol")}
                value={symbol}
                onValueChange={(value) => setSymbol(value as Stream["symbol"])}
              >
                <DropdownOption value="BTCUSDT">
                  {text("option.btc")}
                </DropdownOption>
                <DropdownOption value="ETHUSDT">
                  {text("option.eth")}
                </DropdownOption>
                <DropdownOption value="MUUSDT">MU / USDT</DropdownOption>
              </Dropdown>
            </label>
            <label className="wh-window">
              {text("field.window")}
              <input
                aria-label={text("field.window")}
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
            <div className="wh-price">
              <span>{text("price.label")}</span>
              <strong>
                {money(analysis?.bars.at(-1)?.bar.close, missing)}{" "}
                <small>USDT</small>
              </strong>
            </div>
          </div>
          <div className="wh-meta">
            <span className="wh-badge">{text(source === "bybit" ? "badge.bybitSpot" : "badge.perpetual")}</span>
            <span className="wh-badge">
              {offline
                ? text("frame.offline")
                : selectedId
                  ? text("frame.saved")
                  : labeled(text, "state", frameState)}
            </span>
            {!selectedId && <small>{text("meta.autoRefresh")}</small>}
          </div>
          {(offline ||
            actionError ||
            saved.isError ||
            workspace.data?.refresh_job?.error_code) && (
            <div className="wh-alert" role="alert">
              {offline
                ? text("alert.offline", {
                    message:
                      workspace.error?.message ??
                      status.error?.message ??
                      text("alert.unavailable"),
                  })
                : actionError ||
                  (saved.isError ? saved.error.message : "") ||
                  text("alert.refresh", {
                    code:
                      workspace.data?.refresh_job?.error_code ??
                      text("error.unknown"),
                  })}
            </div>
          )}
          {latestJob && latestJob.state !== "succeeded" && (
            <div className="wh-task" role="status">
              <span>
                {text("task.line", {
                  state: labeled(text, "job", latestJob.state),
                  attempts: latestJob.attempts,
                })}
              </span>
              <span>
                {latestJob.request.kind === "analyze"
                  ? text("task.stored")
                  : latestJob.checkpoint_batch_id
                    ? text("task.checkpoint")
                    : text("task.awaiting")}
              </span>
              {latestJob.state === "retry_wait" && (
                <span>
                  {text("task.retry", {
                    time: stamp(latestJob.next_attempt_at, missing),
                  })}
                </span>
              )}
            </div>
          )}
          <div
            className="wh-methods"
            role="tablist"
            aria-label={text("method.group")}
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
            <div role="group" aria-label={text("timeframe.group")}>
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
              {text("visibleBars")}
              <Dropdown
                aria-label={text("visibleBars")}
                value={visibleBars}
                onValueChange={(value) => setVisibleBars(Number(value))}
              >
                <DropdownOption value="0">{text("range.auto")}</DropdownOption>
                <DropdownOption value="50">50</DropdownOption>
                <DropdownOption value="100">100</DropdownOption>
                <DropdownOption value="200">200</DropdownOption>
                <DropdownOption value="500">500</DropdownOption>
                <DropdownOption value="-1">{text("range.all")}</DropdownOption>
              </Dropdown>
            </label>
            <span className="wh-muted">
              24/7 · UTC ·{" "}
              {selectedId ? text("capture.replay") : text("capture.latest")}
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
                  {text("chart.closedCount", {
                    tf: timeframe.toUpperCase(),
                    count: analysis?.bars.length ?? 0,
                  })}
                </span>
              </div>
              {analysis ? (
                <MarketChart
                  key={`${source}:${symbol}:${timeframe}:${selectedId ?? "live"}`}
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
                      ? text("chart.loadingSaved")
                      : pending?.kind === "refresh" ||
                          submitting ||
                          activeStates.has(latestJob?.state ?? "")
                        ? text("chart.fetching", {
                            tf: timeframe.toUpperCase(),
                          })
                        : text("chart.none", { tf: timeframe.toUpperCase() })}
                  </p>
                </div>
              )}
              {analysis && (
                <details className="wh-chart-data">
                  <summary>{text("chart.timestamps")}</summary>
                  <div className="wh-provenance">
                    <div>
                      <span>{text("stamp.closed")}</span>
                      <strong>
                        {stamp(analysis.closed_bar_time, missing)}
                      </strong>
                    </div>
                    <div>
                      <span>{text("stamp.forming")}</span>
                      <strong>
                        {stamp(analysis.forming_bar_time, missing)}
                      </strong>
                    </div>
                    <div>
                      <span>{text("stamp.acquired")}</span>
                      <strong>{stamp(analysis.fetched_at, missing)}</strong>
                    </div>
                    <div>
                      <span>{text("stamp.nextClose")}</span>
                      <strong>
                        {stamp(analysis.expected_next_close, missing)}
                      </strong>
                    </div>
                  </div>
                </details>
              )}
            </div>
            <aside
              className="wh-inspector"
              aria-label={text("inspector.label")}
            >
              <span className="wh-eyebrow">{text("inspector.eyebrow")}</span>
              <h2>
                {method === "levels"
                  ? text("inspector.levels")
                  : method === "td"
                    ? text("inspector.td")
                    : text("inspector.fib")}
              </h2>
              {method === "levels" ? (
                <>
                  <p>{text("inspector.levelsBody")}</p>
                  <Facts
                    entries={[
                      [
                        text("inspector.sma", {
                          window: analysis?.rules.window ?? windowSize,
                        }),
                        money(latestPoint?.sma, missing),
                      ],
                      [
                        text("inspector.priorHigh"),
                        money(latestPoint?.prior_high, missing),
                      ],
                      [
                        text("inspector.priorLow"),
                        money(latestPoint?.prior_low, missing),
                      ],
                      [
                        text("inspector.warmup"),
                        analysis
                          ? text("inspector.warmupValue", {
                              state: analysis.warmup_complete
                                ? text("inspector.warmupComplete")
                                : text("inspector.warmupIncomplete"),
                              count: analysis.warmup_required,
                            })
                          : text("inspector.noDataset"),
                      ],
                      [
                        text("inspector.calculation"),
                        analysis?.rules.engine_version ?? "baseline-v1",
                      ],
                      [
                        text("inspector.signal"),
                        text("inspector.notImplemented"),
                      ],
                    ]}
                  />
                  <p className="wh-muted">{text("inspector.levelsNote")}</p>
                </>
              ) : method === "td" ? (
                <DemarkDetails
                  result={analysis?.demark}
                  selectedId={selectedSequence?.sequence_id ?? null}
                  onSelect={setSequenceId}
                />
              ) : (
                <>
                  <span className="wh-badge wh-amber">
                    {text("inspector.fibBadge")}
                  </span>
                  <p>{text("inspector.fibBody")}</p>
                </>
              )}
              {analysis && (
                <>
                  <h3>{text("quality.title")}</h3>
                  {analysis.issues.length ? (
                    <ul>
                      {analysis.issues.map((issue) => (
                        <li key={issue}>{issueText(text, issue)}</li>
                      ))}
                    </ul>
                  ) : (
                    <p>{text("quality.none")}</p>
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
          {method === "td" && (
            <RegimeCheck stream={stream} rules={rules} live={!selectedId} />
          )}
          <section className="wh-replay">
            <div className="wh-section-title">
              <div>
                <span className="wh-eyebrow">{text("replay.eyebrow")}</span>
                <h2>{text("replay.title")}</h2>
              </div>
              {analysis && (
                <a
                  href={`${PREFIX}/snapshots/${analysis.snapshot_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {text("replay.json")}
                </a>
              )}
            </div>
            <label>
              {text("replay.saved")}
              <Dropdown
                aria-label={text("replay.saved")}
                value={selectedId ?? ""}
                onValueChange={(value) => {
                  setSelectedId(value || null);
                  setMarketCutoff("");
                  setCutoffEdited(false);
                }}
              >
                <DropdownOption value="">
                  {text("replay.latest")}
                </DropdownOption>
                {history.data?.map((item) => (
                  <DropdownOption
                    key={item.snapshot_id}
                    value={item.snapshot_id}
                  >
                    {stamp(item.market_at, missing)} ·{" "}
                    {text("replay.window", { window: item.rules.window })} ·{" "}
                    {text("replay.bars", { count: item.bar_count })} ·{" "}
                    {item.rules.demark
                      ? text("engine.sequential")
                      : text("engine.baseline")}{" "}
                    · {labeled(text, "data", item.data_state)}
                  </DropdownOption>
                ))}
              </Dropdown>
            </label>
            {analysis && (
              <>
                <div className="wh-cutoffs">
                  <label>
                    {text("replay.cutoff")}
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
                    {text("replay.knowledge")}
                    <Dropdown
                      aria-label={text("replay.knowledge")}
                      value={knowledgeMode}
                      onValueChange={(value) => setKnowledgeMode(value)}
                    >
                      <DropdownOption value="pinned">
                        {text("replay.pinned")}
                      </DropdownOption>
                      <DropdownOption value="as_known">
                        {text("replay.asKnown")}
                      </DropdownOption>
                    </Dropdown>
                  </label>
                  <button
                    disabled={busy || offline || !marketCutoff}
                    onClick={() => void start("analyze")}
                  >
                    {pending?.kind === "analyze"
                      ? text("replay.replaying")
                      : text("replay.run")}
                  </button>
                </div>
                <p className="wh-muted">
                  {text("replay.pinnedNote", {
                    time: stamp(analysis.knowledge_at, missing),
                  })}
                </p>
                <p className="wh-hash">
                  {text("replay.fingerprint", {
                    hash: analysis.input_hash.slice(0, 24),
                    mode: labeled(text, "mode", analysis.mode),
                    engine: analysis.rules.engine_version,
                  })}
                </p>
              </>
            )}
          </section>
          <details className="wh-disclosure">
            <summary>{text("audit.summary")}</summary>
            {events.data && (
              <div className="wh-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>{text("audit.time")}</th>
                      <th>{text("audit.state")}</th>
                      <th>{text("audit.reason")}</th>
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
                {text("audit.batch")}
              </a>
            )}
          </details>
          {analysis && (
            <details className="wh-disclosure">
              <summary>{text("ohlc.summary")}</summary>
              <div className="wh-table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>{text("ohlc.openTime")}</th>
                      <th>{text("ohlc.open")}</th>
                      <th>{text("ohlc.high")}</th>
                      <th>{text("ohlc.low")}</th>
                      <th>{text("ohlc.close")}</th>
                      <th>{text("ohlc.volume")}</th>
                      <th>{text("ohlc.revision")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...analysis.bars].reverse().map((row) => (
                      <tr key={row.revision_id}>
                        <td>{stamp(row.bar.open_time, missing)}</td>
                        <td>{money(row.bar.open, missing)}</td>
                        <td>{money(row.bar.high, missing)}</td>
                        <td>{money(row.bar.low, missing)}</td>
                        <td>{money(row.bar.close, missing)}</td>
                        <td>{money(row.bar.volume, missing)}</td>
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
          <footer className="wh-footer">{text("footer")}</footer>
        </div>
      </PageContent>
    </Page>
  );
}

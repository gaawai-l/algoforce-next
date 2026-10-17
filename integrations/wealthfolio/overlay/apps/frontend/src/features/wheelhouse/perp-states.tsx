import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { getPerpStates, getPerpStatus } from "./client";
import { useWheelhouseText, type MessageKey, type TextFn } from "./i18n";
import { rulesNote } from "./onchain-text";
import { PerpCharts, thresholdsText } from "./perp-charts";
import type {
  PerpCollector,
  PerpState,
  PerpStatesView,
  PerpsStatus,
  PerpTable,
} from "./perps-contract";

type Exchange = PerpStatesView["exchange"];
type StateWindow = PerpStatesView["window"];

// The parameters live in the URL as px / pw / ps; anything else there falls back to the default.
const EXCHANGES: readonly Exchange[] = ["all", "binance", "bybit"];
const WINDOWS: readonly StateWindow[] = ["4h", "8h"];
const SHOWS = ["7", "30"] as const;
type Show = (typeof SHOWS)[number];

const HOURS: Record<StateWindow, number> = { "4h": 4, "8h": 8 };
const BUCKETS: Record<StateWindow, number> = { "4h": 24, "8h": 48 };
const BUCKET_MS = 600_000;
const WIDE = "(min-width: 601px)";

const exchangeKey: Record<Exchange, MessageKey> = {
  all: "perp.exchange.all",
  binance: "perp.exchange.binance",
  bybit: "perp.exchange.bybit",
};
const stateKey: Record<PerpState, MessageKey> = {
  shortsq: "perp.state.shortsq",
  longsq: "perp.state.longsq",
  shortun: "perp.state.shortun",
  longun: "perp.state.longun",
  longbd: "perp.state.longbd",
  shortbd: "perp.state.shortbd",
  spot: "perp.state.spot",
  chop: "perp.state.chop",
};
const whatKey: Record<PerpState, MessageKey> = {
  shortsq: "perp.what.shortsq",
  longsq: "perp.what.longsq",
  shortun: "perp.what.shortun",
  longun: "perp.what.longun",
  longbd: "perp.what.longbd",
  shortbd: "perp.what.shortbd",
  spot: "perp.what.spot",
  chop: "perp.what.chop",
};
const streamKey: Record<PerpCollector["stream"], MessageKey> = {
  binance_liq: "perp.stream.binance_liq",
  bybit_liq: "perp.stream.bybit_liq",
  bybit_trades: "perp.stream.bybit_trades",
};
const seriesKey: Record<string, MessageKey> = {
  "bybit:price": "perp.series.bybitPrice",
  "binance:oi": "perp.series.binanceOi",
  "binance:kline": "perp.series.binanceKline",
  "bybit:oi": "perp.series.bybitOi",
};
// Their side comes from the exchanges' liquidation fields, checked against price in /perps/status.
const SQUEEZES: readonly PerpState[] = ["shortsq", "longsq"];
// The venues whose liquidations a view reads, each checked on its own.
const VENUES: Record<Exchange, readonly ("binance" | "bybit")[]> = {
  all: ["binance", "bybit"],
  binance: ["binance"],
  bybit: ["bybit"],
};

// A view's squeezes are verified by its own venue's check; All venues needs the combined
// verdict. No status or no check yet is not ok.
function verdictOf(status: PerpsStatus | undefined, exchange: Exchange) {
  if (!status) return "pending";
  if (exchange === "all") return status.direction;
  return status.direction_check?.[exchange].verdict ?? "pending";
}

const pick = <T extends string>(
  options: readonly T[],
  value: string | null,
  fallback: T,
) => options.find((option) => option === value) ?? fallback;

const utcMinute = (t: string | number) =>
  new Date(t).toISOString().slice(0, 16).replace("T", " ");
const utcDate = (t: string | number) => new Date(t).toISOString().slice(0, 10);

const seriesName = (text: TextFn, key: string) =>
  key in seriesKey ? text(seriesKey[key]) : key;

// Reason codes from the service; anything unknown is shown as received. `kept` says whether an
// older view is on screen, which a failing host leaves in place.
function reasonText(
  text: TextFn,
  reason: string,
  collectors: PerpCollector[],
  kept: boolean,
) {
  if (reason === "not_derived") return text("perp.reason.notDerived");
  if (reason === "perps_disabled") return text("perp.reason.disabled");
  const series = /^series_missing:(.+)$/.exec(reason);
  if (series)
    return text("perp.reason.seriesMissing", {
      series: seriesName(text, series[1]),
    });
  const rest = /^rest_error:([^:]+):(.+)$/.exec(reason);
  if (rest)
    return text(kept ? "perp.reason.restError" : "perp.reason.restFailing", {
      host: rest[1],
      code: rest[2],
    });
  const down = /^collector_down:(.+)$/.exec(reason);
  const collector = down && collectors.find((item) => item.stream === down[1]);
  if (collector) {
    const name = text(streamKey[collector.stream]);
    return collector.down_since
      ? text("perp.reason.collectorDown", {
          name,
          time: utcMinute(collector.down_since),
        })
      : text("perp.reason.collectorNever", { name });
  }
  return reason;
}

function qcText(text: TextFn, code: string) {
  const missing = /^missing:(.+)$/.exec(code);
  if (missing)
    return text("perp.qc.missing", { series: seriesName(text, missing[1]) });
  const gap = /^gap:(.+):(\d+)$/.exec(code);
  if (gap)
    return text("perp.qc.gap", {
      series: seriesName(text, gap[1]),
      minutes: Number(gap[2]) / 60,
    });
  const quarantined = /^archive_quarantined:(\d+)$/.exec(code);
  if (quarantined)
    return text("perp.qc.quarantined", { count: quarantined[1] });
  return code;
}

// A signed percent and the run's length, e.g. "−2.48% · 4h"; a state without a run reads "—".
// The sign follows the rounded value, so a tiny fall reads 0.00%, never −0.00%.
function maxMove(row: PerpTable["rows"][number], window: StateWindow) {
  if (row.max_move == null) return "—";
  const rounded = Number(row.max_move.toFixed(2));
  const sign = rounded < 0 ? "−" : rounded > 0 ? "+" : "";
  const percent = `${sign}${Math.abs(rounded).toFixed(2)}%`;
  return row.run_blocks == null
    ? percent
    : `${percent} · ${row.run_blocks * HOURS[window]}h`;
}

// Follows the screen width, so a resized or rotated window gets the matching table.
function useWide() {
  const [wide, setWide] = useState(
    () =>
      typeof window.matchMedia !== "function" ||
      window.matchMedia(WIDE).matches,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(WIDE);
    const update = () => setWide(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return wide;
}

function Choice<T extends string>({
  id,
  label,
  options,
  value,
  onPick,
}: {
  id: string;
  label: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onPick: (value: T) => void;
}) {
  return (
    <div className="wh-perp-choice">
      <span id={id}>{label}</span>
      <div className="wh-perp-seg" role="group" aria-labelledby={id}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={option.value === value}
            onClick={() => onPick(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function StatesTable({
  view,
  table,
  wide,
  verified,
}: {
  view: PerpStatesView;
  table: PerpTable;
  wide: boolean;
  verified: boolean;
}) {
  const { text } = useWheelhouseText();
  const last = view.blocks.at(-1);
  // Only a judged block has a state that can still change; O1 judges closed blocks alone, and
  // Table 1 marks the last of them.
  const forming = last?.forming && last.state ? last : null;
  const closed = view.rules.includes("O1");
  const label = (state: PerpState) =>
    SQUEEZES.includes(state) && !verified
      ? text("perp.unverified", { state: text(stateKey[state]) })
      : text(stateKey[state]);
  const marker = text(
    forming
      ? "perp.latestForming"
      : closed
        ? "perp.latestClosed"
        : "perp.latest",
  );
  return (
    <section className="wh-perp-panel" aria-labelledby="wh-perp-table">
      <div className="wh-perp-head">
        <h3 id="wh-perp-table">{text("perp.table.title")}</h3>
        <p className="wh-perp-subtitle">
          {text("perp.table.subtitle", {
            judged: table.judged,
            total: table.in_view,
          })}
          {table.latest_uncovered
            ? ` · ${text(
                closed
                  ? "perp.table.latestClosedUncovered"
                  : "perp.table.latestUncovered",
              )}`
            : ""}
        </p>
      </div>
      <table className="wh-perp-table">
        <thead>
          <tr>
            <th scope="col">{text("perp.table.state")}</th>
            {wide ? <th scope="col">{text("perp.table.what")}</th> : null}
            <th scope="col" className="wh-perp-num">
              {text("perp.table.prob", { days: table.show_days })}
            </th>
            <th scope="col" className="wh-perp-num">
              {text(wide ? "perp.table.move" : "perp.table.moveShort")}
            </th>
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => (
            <tr key={row.state} data-state={row.state}>
              <th scope="row">
                <i
                  className={`wh-perp-swatch wh-perp-swatch--${row.state}`}
                  aria-hidden="true"
                />
                {label(row.state)}
                {table.latest === row.state ? (
                  <span
                    className="wh-perp-latest"
                    role="img"
                    aria-label={marker}
                    title={marker}
                  />
                ) : null}
              </th>
              {wide ? <td>{text(whatKey[row.state])}</td> : null}
              <td className="wh-perp-num">
                {row.share == null ? "—" : `${row.share}%`}
              </td>
              <td className="wh-perp-num">{maxMove(row, view.window)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {wide ? null : (
        <details className="wh-perp-what">
          <summary>{text("perp.table.what")}</summary>
          <dl>
            {table.rows.map((row) => (
              <div key={row.state}>
                <dt>{text(stateKey[row.state])}</dt>
                <dd>{text(whatKey[row.state])}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {forming ? (
        <p className="wh-muted wh-perp-forming">
          {text("perp.forming", {
            buckets: forming.buckets,
            total: BUCKETS[view.window],
          })}
        </p>
      ) : null}
      <div className="wh-perp-read">
        {(
          [
            ["seller.read.shows", "perp.table.shows"],
            ["seller.read.implies", "perp.table.implies"],
            // O6 ranks each block on the 90 days before it alone.
            [
              "seller.read.how",
              view.rules.includes("O6")
                ? "perp.table.howPast"
                : "perp.table.how",
            ],
          ] as const
        ).map(([heading, body]) => (
          <div key={heading}>
            <h4>{text(heading)}</h4>
            <p>{text(body)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

// Flows → Perp states: the notices about the view, the parameters, then Table 1 and Charts 1–4.
export function PerpStates() {
  const { text } = useWheelhouseText();
  const [search, setSearch] = useSearchParams();
  const exchange = pick(EXCHANGES, search.get("px"), "all");
  const stateWindow = pick(WINDOWS, search.get("pw"), "4h");
  const show: Show = pick(SHOWS, search.get("ps"), "30");
  const wide = useWide();
  const states = useQuery({
    // Both Show spans come in one payload, so Show is not part of the request.
    queryKey: ["wh", "perps", exchange, stateWindow],
    queryFn: ({ signal }) => getPerpStates(exchange, stateWindow, signal),
    refetchInterval: 300000,
    retry: false,
  });
  const status = useQuery({
    queryKey: ["wh", "perps", "status"],
    queryFn: ({ signal }) => getPerpStatus(signal),
    refetchInterval: 60000,
    retry: false,
  });
  // Unknown counts as unverified: a failed status request does not vouch for the direction.
  const checked = status.isError ? undefined : status.data;
  const verified = verdictOf(checked, exchange) === "ok";
  const inverted = VENUES[exchange].filter(
    (venue) => checked?.direction_check?.[venue].verdict === "inverted",
  );
  const set = (name: "px" | "pw" | "ps", value: string) =>
    setSearch(
      (current) => {
        const next = new URLSearchParams(current);
        next.set(name, value);
        return next;
      },
      { replace: true },
    );

  const data = states.data;
  const reasons = (view: PerpStatesView, kept: boolean) => {
    // The collecting banner already says how far collection is.
    const list = view.reasons
      .filter((reason) => !reason.startsWith("collecting:"))
      .map((reason) => reasonText(text, reason, view.collectors, kept));
    return list.length ? (
      <p className="wh-onchain-warn">{list.join(" · ")}</p>
    ) : null;
  };
  let notices: ReactNode;
  let body: ReactNode = null;
  // O6: the thresholds heading the view, shown with the parameters.
  let ranked: ReactNode = null;
  // A failed request wins over older data: the view must not look current when it is not.
  if (states.isError) {
    const failure = String(states.error.message ?? "");
    notices = (
      <>
        <p className="wh-onchain-warn">{text("perp.unavailable")}</p>
        {failure ? <p className="wh-muted">{failure}</p> : null}
      </>
    );
  } else if (!data) {
    notices = <p className="wh-muted">{text("perp.loading")}</p>;
  } else if (data.data_state === "unavailable" || !data.last) {
    notices = (
      <>
        <p className="wh-onchain-warn">{text("perp.unavailable")}</p>
        {reasons(data, false)}
      </>
    );
  } else {
    const through = utcMinute(Date.parse(data.last) + BUCKET_MS);
    // All venues counts a block only once every venue's liquidations are collected.
    const liquidations = data.collectors.filter(
      (collector) => collector.stream !== "bybit_trades",
    );
    const starts = liquidations
      .map((collector) => collector.since)
      .filter((start) => start != null);
    const since =
      starts.length && starts.length === liquidations.length
        ? utcDate(Math.max(...starts.map((start) => Date.parse(start))))
        : text("missing");
    const late = data.data_state === "delayed" || data.data_state === "stale";
    const o6 = data.rules.includes("O6");
    // Under O6 collecting reads the liquidation sample of the block heading the view, as the
    // service's reason does; v1 counts the covered blocks.
    const collected = o6
      ? data.thresholds && data.thresholds.n_liq / (24 / HOURS[data.window])
      : data.covered_days;
    notices = (
      <>
        <p className="wh-perp-meta">
          {text("perp.meta", { time: through, since })}
        </p>
        {rulesNote(text, data).map((line) => (
          <p key={line} className="wh-perp-meta">
            {line}
          </p>
        ))}
        {data.collectors.length ? (
          <p className="wh-muted">
            {text("perp.coverage", {
              list: data.collectors
                .map((collector) =>
                  text("perp.coverageDays", {
                    name: text(streamKey[collector.stream]),
                    days: collector.covered_days.toFixed(1),
                  }),
                )
                .join(" · "),
            })}
          </p>
        ) : null}
        {data.exchange === "bybit" ? null : (
          <p className="wh-muted">{text("perp.binanceNote")}</p>
        )}
        {late ? (
          <p className="wh-onchain-warn">
            {text(
              data.data_state === "delayed" ? "perp.delayed" : "perp.stale",
              { time: through },
            )}
          </p>
        ) : null}
        {data.qc.length ? (
          <p className="wh-onchain-warn">
            {text("perp.qc", {
              count: data.qc.length,
              list: data.qc.map((code) => qcText(text, code)).join(", "),
            })}
          </p>
        ) : null}
        {reasons(data, true)}
        {inverted.map((venue) => (
          <p key={venue} className="wh-onchain-warn">
            {text("perp.inverted", { venue: text(exchangeKey[venue]) })}
          </p>
        ))}
        {data.collecting ? (
          <p className="wh-flows-note wh-flows-note--pending">
            {text(
              data.exchange === "binance"
                ? "perp.collecting"
                : "perp.collectingTrades",
              {
                days:
                  collected == null ? text("missing") : collected.toFixed(1),
              },
            )}
          </p>
        ) : null}
      </>
    );
    if (o6 && data.thresholds)
      ranked = (
        <div className="wh-perp-thresholds">
          <p>
            <span>{text("perp.thresholds")}</span>{" "}
            {thresholdsText(text, data.thresholds)}
          </p>
          <p className="wh-muted">
            {text(
              data.rules.includes("O1")
                ? "perp.thresholds.ofLatestClosed"
                : "perp.thresholds.ofLatest",
              {
                liq: data.thresholds.n_liq,
                px: data.thresholds.n_px,
                oi: data.thresholds.n_oi,
              },
            )}
          </p>
        </div>
      );
    const table = data.tables.find((item) => item.show_days === Number(show));
    if (!table)
      body = (
        <p className="wh-onchain-warn">
          {text("perp.showMissing", { days: show })}
        </p>
      );
    else
      body = (
        <>
          {/* While collecting with nothing judged there is no Table 1 to show. Under O6 earlier
              blocks can be judged while the view collects: those are shown. */}
          {data.collecting &&
          !data.blocks.some((block) => block.state != null) ? null : (
            <StatesTable
              view={data}
              table={table}
              wide={wide}
              verified={verified}
            />
          )}
          <PerpCharts view={data} show={table.show_days} verified={verified} />
        </>
      );
  }

  return (
    <div className="wh-perp">
      {notices}
      <section className="wh-perp-panel" aria-labelledby="wh-perp-params">
        <h3 id="wh-perp-params">{text("perp.params")}</h3>
        <div className="wh-perp-choices">
          <Choice
            id="wh-perp-px"
            label={text("perp.exchange")}
            options={EXCHANGES.map((value) => ({
              value,
              label: text(exchangeKey[value]),
            }))}
            value={exchange}
            onPick={(value) => set("px", value)}
          />
          <Choice
            id="wh-perp-pw"
            label={text("perp.window")}
            options={WINDOWS.map((value) => ({ value, label: value }))}
            value={stateWindow}
            onPick={(value) => set("pw", value)}
          />
          <Choice
            id="wh-perp-ps"
            label={text("perp.show")}
            options={SHOWS.map((value) => ({ value, label: `${value}d` }))}
            value={show}
            onPick={(value) => set("ps", value)}
          />
        </div>
        {ranked}
      </section>
      {body}
    </div>
  );
}

import {
  memo,
  useMemo,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { getSellSide } from "./client";
import { useWheelhouseText, type MessageKey, type TextFn } from "./i18n";
import type { SellSideView } from "./onchain-contract";
import { reasonText, rulesNote } from "./onchain-text";
import { timeTicks, useChartWidth } from "./seller-charts";
import {
  DEFAULT_CHOICE,
  EXCLUDES,
  LEGS,
  MEASURES,
  SMOOTHINGS,
  SPANS,
  axisValue,
  buildRows,
  fmtPct,
  fmtVal,
  footLine,
  heightFor,
  niceDomain,
  si,
  ticks,
  type Choice,
  type Leg,
  type SellSideRow,
} from "./sell-side";

type Mode = "relative" | "absolute";
const HOUR = 3_600_000;
const round = (value: number) => Math.round(value * 100) / 100;
const utcStamp = (t: number) =>
  new Date(t).toISOString().slice(0, 16).replace("T", " ");

const COPY = {
  relative: {
    key: "a",
    title: "sellside.a.title",
    shows: "sellside.a.shows",
    implies: "sellside.a.implies",
    how: "sellside.a.how",
  },
  absolute: {
    key: "b",
    title: "sellside.b.title",
    shows: "sellside.b.shows",
    implies: "sellside.b.implies",
    how: "sellside.b.how",
  },
} as const satisfies Record<Mode, Record<string, string>>;
const LEG_NAMES = {
  LP: "sellside.leg.LP",
  LL: "sellside.leg.LL",
  SP: "sellside.leg.SP",
  SL: "sellside.leg.SL",
} as const satisfies Record<Leg, MessageKey>;

interface Frame {
  left: number;
  top: number;
  plotW: number;
  plotH: number;
  t0: number;
  t1: number;
  slot: number;
  x: (t: number) => number;
}

function frame(width: number, height: number, rows: SellSideRow[]): Frame {
  const compact = width < 500;
  const left = compact ? 44 : 60;
  const right = compact ? 44 : 56;
  const top = 10;
  const bottom = 24;
  const plotW = Math.max(40, width - left - right);
  const t0 = rows[0].t;
  const t1 = rows[rows.length - 1].t;
  // One slot per clock hour, so a dropped hour leaves a gap instead of shifting its neighbours.
  const slot = plotW / ((t1 - t0) / HOUR + 1);
  return {
    left,
    top,
    plotW,
    plotH: height - top - bottom,
    t0,
    t1,
    slot,
    x: (t: number) => left + ((t - t0) / HOUR) * slot + slot / 2,
  };
}

function nearest(rows: SellSideRow[], t: number) {
  let lo = 0;
  let hi = rows.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].t < t) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && t - rows[lo - 1].t < rows[lo].t - t ? lo - 1 : lo;
}

interface LayerProps {
  mode: Mode;
  rows: SellSideRow[];
  choice: Choice;
  formingT: number | null;
  width: number;
  height: number;
}

// Everything that does not move with the pointer; memoized so reading an hour does not redraw
// thousands of bars.
const Layer = memo(function Layer({
  mode,
  rows,
  choice,
  formingT,
  width,
  height,
}: LayerProps) {
  const f = frame(width, height, rows);
  const relative = mode === "relative";
  const peak = Math.max(...rows.map((row) => row.tot));
  const [, top] = relative ? [0, 1] : niceDomain(0, peak || 1);
  const y = (v: number) => f.top + f.plotH * (1 - v / top);
  const yTicks = ticks(0, top, 5);
  const barW = Math.max(0.6, f.slot - (rows.length > 240 ? 0 : 1));

  const prices = rows.map((row) => row.px);
  const pMin = Math.min(...prices);
  const pMax = Math.max(...prices);
  const pPad = (pMax - pMin) * 0.08 || 1;
  const pLo = pMin - pPad;
  const pHi = pMax + pPad;
  const py = (v: number) => f.top + f.plotH * (1 - (v - pLo) / (pHi - pLo));
  // As the original's d3 line: a row that is not one hour after the one before it in the payload
  // is left out and breaks the line; rows dropped from the chart in between do not.
  let pricePath = "";
  let open = false;
  rows.forEach((row, i) => {
    if (!row.contig && i > 0) {
      open = false;
      return;
    }
    pricePath += `${open ? "L" : "M"}${round(f.x(row.t))},${round(py(row.px))}`;
    open = true;
  });

  const forming = formingT == null ? undefined : rows.find((r) => r.t === formingT);
  const formingTop = forming ? y(relative ? 1 : forming.tot) : 0;

  return (
    <>
      {yTicks.map((v) => (
        <g key={v}>
          <line
            className="wh-seller-grid"
            x1={f.left}
            x2={f.left + f.plotW}
            y1={round(y(v))}
            y2={round(y(v))}
          />
          <text
            className="wh-seller-tick"
            x={f.left - 6}
            y={round(y(v) + 3.5)}
            textAnchor="end"
          >
            {relative ? `${Math.round(v * 100)}%` : axisValue(v, choice.measure)}
          </text>
        </g>
      ))}
      {timeTicks(f.t0, f.t1, Math.max(2, Math.floor(f.plotW / 64))).map(
        ([t, label]) => (
          <text
            key={t}
            className="wh-seller-tick"
            x={round(f.x(t))}
            y={height - 8}
            textAnchor="middle"
          >
            {label}
          </text>
        ),
      )}
      <text className="wh-seller-tick" x="2" y={height - 8}>
        UTC
      </text>
      {rows.map((row) => {
        let acc = 0;
        const x = round(f.x(row.t) - barW / 2);
        return (
          <g key={row.t}>
            {LEGS.filter((leg) => choice.shown.includes(leg)).map((leg) => {
              const v = relative ? row.vals[leg] / row.tot : row.vals[leg];
              const from = acc;
              acc += v;
              return v > 0 ? (
                <rect
                  key={leg}
                  className={`wh-ss-bar wh-ss-bar--${leg}`}
                  x={x}
                  y={round(y(acc))}
                  width={round(barW)}
                  height={round(y(from) - y(acc))}
                />
              ) : null;
            })}
          </g>
        );
      })}
      <path className="wh-seller-price" d={pricePath} />
      {ticks(pLo, pHi, 5).map((v) => (
        <text
          key={v}
          className="wh-seller-tick wh-seller-tick--price"
          x={f.left + f.plotW + 6}
          y={round(py(v) + 3.5)}
        >
          {`$${si(v)}`}
        </text>
      ))}
      {forming ? (
        <rect
          className="wh-seller-forming"
          data-forming="true"
          x={round(f.x(forming.t) - Math.max(barW + 2, 5) / 2)}
          y={round(formingTop)}
          width={round(Math.max(barW + 2, 5))}
          height={round(f.top + f.plotH - formingTop)}
        />
      ) : null}
    </>
  );
});

function Plot({
  mode,
  rows,
  choice,
  formingT,
  label,
  hover,
  onHover,
}: Omit<LayerProps, "width" | "height"> & {
  label: string;
  hover: number | null;
  onHover: (index: number | null) => void;
}) {
  const [ref, width] = useChartWidth();
  const height = heightFor(width);
  const f = frame(width, height, rows);
  const at = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return;
    const px = ((event.clientX - box.left) / box.width) * width;
    onHover(nearest(rows, f.t0 + ((px - f.left) / f.slot - 0.5) * HOUR));
  };
  const key = (event: KeyboardEvent<SVGSVGElement>) => {
    const last = rows.length - 1;
    const current = hover ?? last;
    const next: Record<string, number | null> = {
      ArrowLeft: Math.max(0, current - 1),
      ArrowRight: Math.min(last, current + 1),
      Home: 0,
      End: null,
      Escape: null,
    };
    if (!(event.key in next)) return;
    event.preventDefault();
    onHover(next[event.key]);
  };
  return (
    <svg
      ref={ref}
      className="wh-seller-svg"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={label}
      tabIndex={0}
      data-points={rows.length}
      onPointerMove={at}
      onPointerDown={at}
      onPointerLeave={(event) => {
        if (event.pointerType === "mouse") onHover(null);
      }}
      onKeyDown={key}
      onBlur={() => onHover(null)}
    >
      <Layer
        mode={mode}
        rows={rows}
        choice={choice}
        formingT={formingT}
        width={width}
        height={height}
      />
      {hover != null && rows[hover] ? (
        <line
          className="wh-seller-cursor"
          x1={round(f.x(rows[hover].t))}
          x2={round(f.x(rows[hover].t))}
          y1={f.top}
          y2={f.top + f.plotH}
        />
      ) : null}
    </svg>
  );
}

export function Segments<T extends string | number>({
  label,
  options,
  value,
  name,
  onPick,
  title,
}: {
  label: string;
  options: readonly T[];
  value: T;
  name: (option: T) => string;
  onPick: (option: T) => void;
  // A tooltip for an option whose short name needs one.
  title?: (option: T) => string | undefined;
}) {
  return (
    <div className="wh-ss-control">
      <span className="wh-ss-label">{label}</span>
      <div className="wh-seller-span" role="group" aria-label={label}>
        {options.map((option) => (
          <button
            key={String(option)}
            type="button"
            aria-pressed={option === value}
            title={title?.(option)}
            onClick={() => onPick(option)}
          >
            {name(option)}
          </button>
        ))}
      </div>
    </div>
  );
}

function Controls({
  choice,
  onChoice,
  text,
}: {
  choice: Choice;
  onChoice: (next: Partial<Choice>) => void;
  text: TextFn;
}) {
  return (
    <div className="wh-ss-controls">
      <Segments
        label={text("sellside.span")}
        options={SPANS.map((span) => span.rows)}
        value={choice.span}
        name={(rows) => SPANS.find((span) => span.rows === rows)?.label ?? ""}
        onPick={(span) => onChoice({ span })}
      />
      <Segments
        label={text("sellside.smoothing")}
        options={SMOOTHINGS}
        value={choice.smoothing as (typeof SMOOTHINGS)[number]}
        name={(hours) => `${hours}h`}
        onPick={(smoothing) => onChoice({ smoothing })}
      />
      <Segments
        label={text("sellside.measure")}
        options={MEASURES}
        value={choice.measure}
        name={(measure) => text(`sellside.measure.${measure}`)}
        onPick={(measure) => onChoice({ measure })}
      />
      <Segments
        label={text("sellside.exclude")}
        options={EXCLUDES}
        value={choice.exclude}
        name={(exclude) => text(`sellside.exclude.${exclude || "off"}`)}
        onPick={(exclude) => onChoice({ exclude })}
      />
    </div>
  );
}

function Panel({
  mode,
  view,
  rows,
  choice,
  onChoice,
}: {
  mode: Mode;
  view: SellSideView;
  rows: SellSideRow[];
  choice: Choice;
  onChoice: (next: Partial<Choice>) => void;
}) {
  const { text } = useWheelhouseText();
  const [hover, setHover] = useState<number | null>(null);
  const copy = COPY[mode];
  const title = text(copy.title);
  const index = hover != null && hover < rows.length ? hover : null;
  const row = rows[index ?? rows.length - 1];
  const formingT = view.forming_at ? Date.parse(view.forming_at) : null;
  const shownCount = choice.shown.length;
  const toggle = (leg: Leg) => {
    const on = choice.shown.includes(leg);
    // Never an empty stack: the last leg shown stays.
    if (on && shownCount === 1) return;
    onChoice({
      shown: LEGS.filter((item) => (item === leg ? !on : choice.shown.includes(item))),
    });
  };
  const change = (next: Partial<Choice>) => {
    setHover(null);
    onChoice(next);
  };

  return (
    <section
      className="wh-seller-panel"
      data-chart={`sellside-${copy.key}`}
      aria-labelledby={`wh-sellside-${copy.key}`}
    >
      <div className="wh-seller-head">
        <h3 id={`wh-sellside-${copy.key}`}>{title}</h3>
      </div>
      <Controls choice={choice} onChoice={change} text={text} />
      {mode === "absolute" ? (
        <p className="wh-ss-both">{text("sellside.both")}</p>
      ) : null}
      {row ? (
        <>
          <Plot
            mode={mode}
            rows={rows}
            choice={choice}
            formingT={formingT}
            label={text("seller.aria", { title })}
            hover={index}
            onHover={setHover}
          />
          <div className="wh-seller-legend" aria-live="polite">
            {LEGS.map((leg) => {
              const on = choice.shown.includes(leg);
              const value = !on
                ? text("sellside.off")
                : mode === "relative"
                  ? fmtPct(row.vals[leg] / row.tot)
                  : fmtVal(row.vals[leg], choice.measure);
              return (
                <button
                  key={leg}
                  type="button"
                  className="wh-ss-leg wh-seller-key"
                  aria-pressed={on}
                  title={text("sellside.toggle")}
                  onClick={() => toggle(leg)}
                >
                  <i
                    className={`wh-seller-swatch wh-ss-swatch--${leg}`}
                    aria-hidden="true"
                  />
                  {text(LEG_NAMES[leg])} <b>{value}</b>
                </button>
              );
            })}
            <span className="wh-seller-key">
              <i
                className="wh-seller-swatch wh-seller-swatch--price"
                aria-hidden="true"
              />
              {text("seller.price")}{" "}
              <b>{`$${Math.round(row.px).toLocaleString("en-US")}`}</b>
            </span>
          </div>
          {mode === "relative" && shownCount < LEGS.length ? (
            <p className="wh-ss-note">
              {text(shownCount === 1 ? "sellside.visibleOne" : "sellside.visible", {
                n: shownCount,
              })}
            </p>
          ) : null}
          <p className="wh-ss-foot">{footLine(text, row, choice)}</p>
        </>
      ) : (
        <p className="wh-muted">{text("seller.noData")}</p>
      )}
      <div className="wh-seller-read">
        {(
          [
            ["seller.read.shows", copy.shows],
            ["seller.read.implies", copy.implies],
            ["seller.read.how", copy.how],
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

function Charts({ view }: { view: SellSideView }) {
  // One set of choices drives both charts, as on the original: they draw the same numbers.
  const [choice, setChoice] = useState<Choice>(DEFAULT_CHOICE);
  const rows = useMemo(() => buildRows(view, choice), [view, choice]);
  const onChoice = (next: Partial<Choice>) =>
    setChoice((current) => ({ ...current, ...next }));
  return (
    <>
      {(["relative", "absolute"] as const).map((mode) => (
        <Panel
          key={mode}
          mode={mode}
          view={view}
          rows={rows}
          choice={choice}
          onChoice={onChoice}
        />
      ))}
    </>
  );
}

export function SellSideCharts() {
  const { text } = useWheelhouseText();
  const query = useQuery({
    queryKey: ["wh", "onchain", "sell-side"],
    queryFn: ({ signal }) => getSellSide(signal),
    // The worker derives once an hour; polling more often only resends the same payload.
    refetchInterval: 300000,
    retry: false,
  });
  const data = query.data;

  // A failed request wins over older data: the charts must not look current when they are not.
  if (query.isError) {
    const failure = String(query.error.message ?? "");
    return (
      <div className="wh-seller wh-sellside">
        <p className="wh-onchain-warn">{text("sellside.unavailable")}</p>
        {failure ? <p className="wh-muted">{failure}</p> : null}
      </div>
    );
  }
  if (!data)
    return (
      <div className="wh-seller wh-sellside">
        <p className="wh-muted">{text("sellside.loading")}</p>
      </div>
    );

  const reasons = data.reasons.length ? (
    <p className="wh-muted">
      {data.reasons.map((reason) => reasonText(text, reason)).join(" · ")}
    </p>
  ) : null;
  if (data.data_state === "unavailable")
    return (
      <div className="wh-seller wh-sellside">
        <p className="wh-onchain-warn">{text("sellside.unavailable")}</p>
        {reasons}
        {data.refreshing ? (
          <p role="status">{text("levels.refreshing")}</p>
        ) : null}
      </div>
    );

  const time = data.last_at ? utcStamp(Date.parse(data.last_at)) : "";
  const late = data.data_state === "delayed" || data.data_state === "stale";
  return (
    <div className="wh-seller wh-sellside">
      <p className="wh-seller-meta">
        {text("seller.meta", { time: time || text("missing") })}
        {data.forming_at ? (
          <span> · {text(late ? "seller.formingOld" : "seller.forming")}</span>
        ) : null}
      </p>
      {rulesNote(text, data).map((line) => (
        <p key={line} className="wh-seller-meta">
          {line}
        </p>
      ))}
      {late ? (
        <p className="wh-onchain-warn">
          {text(
            data.data_state === "delayed" ? "seller.delayed" : "seller.stale",
            { time: time || text("missing") },
          )}
        </p>
      ) : null}
      {data.qc.length ? (
        <p className="wh-onchain-warn">
          {text("seller.qc", {
            count: data.qc.length,
            list: data.qc.map((code) => text(`seller.qc.${code}`)).join(", "),
          })}
        </p>
      ) : null}
      {data.refreshing ? (
        <p role="status">{text("levels.refreshing")}</p>
      ) : null}
      {reasons}
      <Charts view={data} />
    </div>
  );
}

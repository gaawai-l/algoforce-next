import {
  Fragment,
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { getSellerPressure } from "./client";
import { useWheelhouseText, type MessageKey } from "./i18n";
import type { SellerPressureView } from "./onchain-contract";
import { reasonText } from "./onchain-levels";

type Levels = NonNullable<SellerPressureView["loss_levels"]>;
type ChartKey = "loss" | "share" | "supply";
type Kind = "stack" | "bars" | "line";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
// The last N hourly points shown for each span.
const SPANS = [
  { label: "7d", points: 168 },
  { label: "30d", points: 720 },
  { label: "90d", points: 2160 },
] as const;
const DEFAULT_SPAN = 720;

// A row is one hour of one chart; `parts` is [LTH, STH] for the stacked chart and [value] otherwise.
interface Row {
  at: string;
  t: number;
  parts: number[];
}
interface Pt {
  t: number;
  v: number;
}

const SCALES: [number, string][] = [
  [1e9, "B"],
  [1e6, "M"],
  [1e3, "K"],
];
// Axis labels: $41.3M with one decimal. The unit is picked from the rounded value so 999,960
// reads $1.0M, never $1000.0K.
export function compactUsd(value: number, decimals: number) {
  const abs = Math.abs(value);
  const [divisor, unit] = SCALES.find(
    ([d]) => Number((abs / d).toFixed(decimals)) >= 1,
  ) ?? [1, ""];
  return `${value < 0 ? "−" : ""}$${(abs / divisor).toFixed(decimals)}${unit}`;
}
const SI = ["", "k", "M", "B"];
// Chart 1 amounts as the original prints them (d3 ".3s"): three significant digits and a lowercase
// SI suffix, the unit picked after rounding so 999,950 reads $1.00M. The original shows billions
// as B. The amounts are whole hundreds of dollars, so nothing lies between $0 and $1.
export function sigUsd(value: number) {
  if (value === 0) return "$0";
  const [digits, power] = Math.abs(value).toExponential(2).split("e");
  const tier = Math.min(SI.length - 1, Math.floor(Number(power) / 3));
  const scaled = Number(digits) * 10 ** (Number(power) - tier * 3);
  return `${value < 0 ? "−" : ""}$${scaled.toPrecision(3)}${SI[tier]}`;
}
export const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
// The original rounds the price to one decimal.
export const usdPrice = (value: number) =>
  `$${value.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`;
// Axis labels drop a meaningless ".0".
const trim = (label: string) => label.replace(/\.0+(?=[%BMK]?$)/, "");
const axisUsd = (value: number) => trim(compactUsd(value, 1));
const axisPercent = (value: number) => trim(percent(value));

const utcStamp = (t: number) =>
  new Date(t).toISOString().slice(0, 16).replace("T", " ");
const utcDay = (t: number) => new Date(t).toISOString().slice(5, 10);
const utcClock = (t: number) => new Date(t).toISOString().slice(11, 16);

// Consecutive points exactly one hour apart stay in one run; any other step breaks the line.
function runs(points: Pt[]) {
  const out: Pt[][] = [];
  for (const point of points) {
    const run = out[out.length - 1];
    if (run && point.t - run[run.length - 1].t === HOUR) run.push(point);
    else out.push([point]);
  }
  return out;
}

function niceTicks(lo: number, hi: number, count: number) {
  const raw = (hi - lo) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ??
    10 * magnitude;
  const ticks: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step)
    ticks.push(Number(v.toFixed(12)));
  return ticks;
}

// UTC midnights inside the range, thinned so the labels fit; short ranges fall back to the ends.
function timeTicks(t0: number, t1: number, room: number): [number, string][] {
  const first = Math.ceil(t0 / DAY) * DAY;
  const midnights = first <= t1 ? Math.floor((t1 - first) / DAY) + 1 : 0;
  if (!midnights)
    return [
      [t0, utcClock(t0)],
      [t1, utcClock(t1)],
    ];
  const step =
    [1, 2, 3, 5, 7, 10, 15, 30].find((s) => Math.ceil(midnights / s) <= room) ??
    30;
  const out: [number, string][] = [];
  for (let t = first; t <= t1; t += step * DAY) out.push([t, utcDay(t)]);
  return out;
}

function nearest(rows: Row[], t: number) {
  let lo = 0;
  let hi = rows.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].t < t) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && t - rows[lo - 1].t < rows[lo].t - t ? lo - 1 : lo;
}

const round = (value: number) => Math.round(value * 100) / 100;
const isNumber = (value: number | null | undefined): value is number =>
  value != null;

function frame(width: number, height: number, rows: Row[]) {
  const compact = width < 500;
  const left = compact ? 40 : 52;
  const right = compact ? 48 : 58;
  const top = 10;
  const bottom = 24;
  const plotW = Math.max(40, width - left - right);
  const t0 = rows[0].t;
  const t1 = rows[rows.length - 1].t;
  // One slot per hour of the span, so a missing hour leaves a gap instead of shifting its neighbours.
  const slot = plotW / ((t1 - t0) / HOUR + 1);
  return {
    left,
    right,
    top,
    bottom,
    plotW,
    plotH: height - top - bottom,
    t0,
    t1,
    slot,
    x: (t: number) => left + ((t - t0) / HOUR) * slot + slot / 2,
  };
}

interface LayerProps {
  kind: Kind;
  rows: Row[];
  price: Pt[];
  levels: Levels | null;
  formingT: number | null;
  axis: (value: number) => string;
  width: number;
  height: number;
}

// The part of a chart that does not change with the pointer; memoized so reading one hour does
// not redraw thousands of bars.
const Layer = memo(function Layer({
  kind,
  rows,
  price,
  levels,
  formingT,
  axis,
  width,
  height,
}: LayerProps) {
  const f = frame(width, height, rows);
  const marks = [levels?.p95, levels?.p75].filter(isNumber);
  const values = rows.map((row) =>
    kind === "stack" ? row.parts[0] + row.parts[1] : row.parts[0],
  );
  let lo = 0;
  let hi = Math.max(...values, ...marks);
  if (kind === "line") {
    lo = Math.min(...values, ...marks);
    const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.05 || 1;
    hi += pad;
    lo = lo >= 0 ? Math.max(0, lo - pad) : lo - pad;
  } else hi = hi > 0 ? hi * 1.06 : 1;
  const y = (v: number) => f.top + f.plotH * (1 - (v - lo) / (hi - lo));
  const barW = Math.max(1, f.slot * 0.78);
  const lineY = f.top + f.plotH;

  // The price has its own scale on the right axis; without price points there is none.
  const prices = price.map((point) => point.v);
  const pMin = Math.min(...prices);
  const pMax = Math.max(...prices);
  const pPad = (pMax - pMin) * 0.06 || 1;
  const py = (v: number) =>
    f.top + f.plotH * (1 - (v - (pMin - pPad)) / (pMax + pPad - (pMin - pPad)));

  const path = (points: Pt[], yOf: (v: number) => number) =>
    runs(points)
      .map((run) =>
        run.length === 1
          ? `M${round(f.x(run[0].t))},${round(yOf(run[0].v))}L${round(f.x(run[0].t))},${round(yOf(run[0].v))}`
          : run
              .map(
                (p, i) =>
                  `${i ? "L" : "M"}${round(f.x(p.t))},${round(yOf(p.v))}`,
              )
              .join(""),
      )
      .join("");

  const forming =
    formingT == null ? undefined : rows.find((r) => r.t === formingT);
  let outline = null;
  if (forming) {
    const cx = f.x(forming.t);
    const total =
      kind === "stack" ? forming.parts[0] + forming.parts[1] : forming.parts[0];
    if (kind === "line") {
      outline = (
        <circle
          className="wh-seller-forming"
          data-forming="true"
          data-at={forming.at}
          cx={round(cx)}
          cy={round(y(total))}
          r="4"
        />
      );
    } else {
      const w = Math.max(barW + 2, 5);
      const top = Math.min(y(total), lineY - 3);
      outline = (
        <rect
          className="wh-seller-forming"
          data-forming="true"
          data-at={forming.at}
          x={round(cx - w / 2)}
          y={round(top)}
          width={round(w)}
          height={round(lineY - top)}
        />
      );
    }
  }

  return (
    <>
      {niceTicks(lo, hi, 4).map((v) => (
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
            {axis(v)}
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
      {kind === "stack" &&
        rows.map((row) => {
          const [lth, sth] = row.parts;
          const x = round(f.x(row.t) - barW / 2);
          const yLth = y(lth);
          const yTop = y(lth + sth);
          return (
            <Fragment key={row.at}>
              {lth > 0 && (
                <rect
                  className="wh-seller-bar wh-seller-bar--lth"
                  x={x}
                  y={round(yLth)}
                  width={round(barW)}
                  height={round(y(0) - yLth)}
                />
              )}
              {sth > 0 && (
                <rect
                  className="wh-seller-bar wh-seller-bar--sth"
                  x={x}
                  y={round(yTop)}
                  width={round(barW)}
                  height={round(yLth - yTop)}
                />
              )}
            </Fragment>
          );
        })}
      {kind === "bars" &&
        rows
          .filter((row) => row.parts[0] > 0)
          .map((row) => (
            <rect
              key={row.at}
              className="wh-seller-bar wh-seller-bar--sth"
              x={round(f.x(row.t) - barW / 2)}
              y={round(y(row.parts[0]))}
              width={round(barW)}
              height={round(y(0) - y(row.parts[0]))}
            />
          ))}
      {kind === "line" && (
        <path
          className="wh-seller-line"
          d={path(
            rows.map((row) => ({ t: row.t, v: row.parts[0] })),
            y,
          )}
        />
      )}
      {isNumber(levels?.p95) && (
        <line
          className="wh-seller-extreme-line"
          x1={f.left}
          x2={f.left + f.plotW}
          y1={round(y(levels.p95))}
          y2={round(y(levels.p95))}
        />
      )}
      {isNumber(levels?.p75) && (
        <line
          className="wh-seller-warning-line"
          x1={f.left}
          x2={f.left + f.plotW}
          y1={round(y(levels.p75))}
          y2={round(y(levels.p75))}
        />
      )}
      {price.length > 0 && (
        <>
          <path className="wh-seller-price" d={path(price, py)} />
          {niceTicks(pMin - pPad, pMax + pPad, 3).map((v) => (
            <text
              key={v}
              className="wh-seller-tick wh-seller-tick--price"
              x={f.left + f.plotW + 6}
              y={round(py(v) + 3.5)}
            >
              {axisUsd(v)}
            </text>
          ))}
        </>
      )}
      {outline}
    </>
  );
});

function useChartWidth() {
  const ref = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(720);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (next && next > 0) setWidth(Math.round(next));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function Plot({
  kind,
  rows,
  price,
  levels,
  formingT,
  axis,
  height,
  label,
  hover,
  onHover,
}: Omit<LayerProps, "width"> & {
  label: string;
  hover: number | null;
  onHover: (index: number | null) => void;
}) {
  const [ref, width] = useChartWidth();
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
      // A finger lifting also leaves; only a mouse that moves away clears the reading.
      onPointerLeave={(event) => {
        if (event.pointerType === "mouse") onHover(null);
      }}
      onKeyDown={key}
      onBlur={() => onHover(null)}
    >
      <Layer
        kind={kind}
        rows={rows}
        price={price}
        levels={levels}
        formingT={formingT}
        axis={axis}
        width={width}
        height={height}
      />
      {hover != null && rows[hover] && (
        <line
          className="wh-seller-cursor"
          x1={round(f.x(rows[hover].t))}
          x2={round(f.x(rows[hover].t))}
          y1={f.top}
          y2={f.top + f.plotH}
        />
      )}
    </svg>
  );
}

const copy = {
  loss: {
    title: "seller.loss.title",
    shows: "seller.loss.shows",
    implies: "seller.loss.implies",
    how: "seller.loss.how",
  },
  share: {
    title: "seller.share.title",
    shows: "seller.share.shows",
    implies: "seller.share.implies",
    how: "seller.share.how",
  },
  supply: {
    title: "seller.supply.title",
    shows: "seller.supply.shows",
    implies: "seller.supply.implies",
    how: "seller.supply.how",
  },
} satisfies Record<ChartKey, Record<string, MessageKey>>;

interface ChartData {
  key: ChartKey;
  kind: Kind;
  height: number;
  rows: Row[];
  levels: Levels | null;
}

function Panel({
  chart,
  price,
  priceAt,
  formingT,
}: {
  chart: ChartData;
  price: Pt[];
  priceAt: Map<number, number>;
  formingT: number | null;
}) {
  const { text } = useWheelhouseText();
  const missing = text("missing");
  const [points, setPoints] = useState<number>(DEFAULT_SPAN);
  const [hover, setHover] = useState<number | null>(null);
  const { key, kind, levels } = chart;
  const rows = useMemo(() => chart.rows.slice(-points), [chart.rows, points]);
  // Price points inside the hours this chart covers; the price axis follows the same window.
  const shownPrice = useMemo(
    () =>
      rows.length
        ? price.filter(
            (p) => p.t >= rows[0].t && p.t <= rows[rows.length - 1].t,
          )
        : [],
    [price, rows],
  );
  const axis = key === "loss" ? axisUsd : axisPercent;
  const amount = (value: number) =>
    key === "loss" ? sigUsd(value) : percent(value);
  const level = (value: number | null | undefined) =>
    value == null ? missing : amount(value);
  const hint = (name: "seller.extremeHint" | "seller.warningHint") =>
    levels ? text(name, { n: levels.n }) : undefined;
  const index = hover != null && hover < rows.length ? hover : null;
  const row = rows[index ?? rows.length - 1];
  const shownPriceValue = row ? priceAt.get(row.t) : undefined;
  const items: { tone: string; label: string; value: string }[] = row
    ? key === "loss"
      ? [
          {
            tone: "sky",
            label: text("seller.loss.lth"),
            value: amount(row.parts[0]),
          },
          {
            tone: "rose",
            label: text("seller.loss.sth"),
            value: amount(row.parts[1]),
          },
        ]
      : [
          {
            tone: key === "share" ? "rose" : "sky",
            label: text(
              key === "share" ? "seller.share.label" : "seller.supply.label",
            ),
            value: amount(row.parts[0]),
          },
        ]
    : [];
  const title = text(copy[key].title);

  return (
    <section
      className="wh-seller-panel"
      data-chart={key}
      aria-labelledby={`wh-seller-${key}`}
    >
      <div className="wh-seller-head">
        <h3 id={`wh-seller-${key}`}>{title}</h3>
        <div
          className="wh-seller-span"
          role="group"
          aria-label={text("seller.span")}
        >
          {SPANS.map((span) => (
            <button
              key={span.label}
              type="button"
              aria-pressed={span.points === points}
              onClick={() => {
                setPoints(span.points);
                setHover(null);
              }}
            >
              {span.label}
            </button>
          ))}
        </div>
        <div className="wh-seller-levels">
          <span>
            {text("seller.extreme")} ·{" "}
            <b className="wh-seller-extreme" title={hint("seller.extremeHint")}>
              {level(levels?.p95)}
            </b>
          </span>
          <span>
            {text("seller.warning")} ·{" "}
            <b className="wh-seller-warning" title={hint("seller.warningHint")}>
              {level(levels?.p75)}
            </b>
          </span>
        </div>
      </div>
      {row ? (
        <>
          <Plot
            kind={kind}
            rows={rows}
            price={shownPrice}
            levels={levels}
            formingT={formingT}
            axis={axis}
            height={chart.height}
            label={text("seller.aria", { title })}
            hover={index}
            onHover={setHover}
          />
          <div className="wh-seller-legend" aria-live="polite">
            <span className="wh-seller-when">
              {index == null
                ? text("seller.latest", { time: utcStamp(row.t) })
                : `${utcStamp(row.t)} UTC`}
            </span>
            {items.map((item) => (
              <span key={item.tone + item.label} className="wh-seller-key">
                <i
                  className={`wh-seller-swatch wh-seller-swatch--${item.tone}`}
                  aria-hidden="true"
                />
                {item.label} <b>{item.value}</b>
              </span>
            ))}
            <span className="wh-seller-key">
              <i
                className="wh-seller-swatch wh-seller-swatch--price"
                aria-hidden="true"
              />
              {text("seller.price")}{" "}
              <b>
                {shownPriceValue == null ? missing : usdPrice(shownPriceValue)}
              </b>
            </span>
          </div>
        </>
      ) : (
        <p className="wh-muted">{text("seller.noData")}</p>
      )}
      <div className="wh-seller-read">
        {(
          [
            ["seller.read.shows", copy[key].shows],
            ["seller.read.implies", copy[key].implies],
            ["seller.read.how", copy[key].how],
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

function toRows<T extends { at: string }>(
  source: T[],
  parts: (item: T) => number[],
): Row[] {
  return source.map((item) => ({
    at: item.at,
    t: Date.parse(item.at),
    parts: parts(item),
  }));
}

function Charts({ view }: { view: SellerPressureView }) {
  const charts = useMemo<ChartData[]>(
    () => [
      {
        key: "loss",
        kind: "stack",
        height: 220,
        rows: toRows(view.loss, (p) => [p.lth, p.sth]),
        levels: view.loss_levels,
      },
      {
        key: "share",
        kind: "bars",
        height: 150,
        rows: toRows(view.share, (p) => [p.value]),
        levels: view.share_levels,
      },
      {
        key: "supply",
        kind: "line",
        height: 150,
        rows: toRows(view.supply, (p) => [p.value]),
        levels: view.supply_levels,
      },
    ],
    [view],
  );
  const price = useMemo<Pt[]>(
    () => view.price.map((p) => ({ t: Date.parse(p.at), v: p.value })),
    [view],
  );
  const priceAt = useMemo(() => new Map(price.map((p) => [p.t, p.v])), [price]);
  const formingT = view.forming_at ? Date.parse(view.forming_at) : null;
  return (
    <>
      {charts.map((chart) => (
        <Panel
          key={chart.key}
          chart={chart}
          price={price}
          priceAt={priceAt}
          formingT={formingT}
        />
      ))}
    </>
  );
}

export function SellerCharts() {
  const { text } = useWheelhouseText();
  const pressure = useQuery({
    queryKey: ["wh", "onchain", "seller-pressure"],
    queryFn: ({ signal }) => getSellerPressure(signal),
    // The worker derives once an hour; polling more often only resends the same payload.
    refetchInterval: 300000,
    retry: false,
  });
  const data = pressure.data;

  // A failed request wins over older data: the charts must not look current when they are not,
  // whatever the error says (it may have no message at all).
  if (pressure.isError) {
    const failure = String(pressure.error.message ?? "");
    return (
      <div className="wh-seller">
        <p className="wh-onchain-warn">{text("seller.unavailable")}</p>
        {failure ? <p className="wh-muted">{failure}</p> : null}
      </div>
    );
  }
  if (!data)
    return (
      <div className="wh-seller">
        <p className="wh-muted">{text("seller.loading")}</p>
      </div>
    );

  const reasons = data.reasons.length ? (
    <p className="wh-muted">
      {data.reasons.map((reason) => reasonText(text, reason)).join(" · ")}
    </p>
  ) : null;
  if (data.data_state === "unavailable")
    return (
      <div className="wh-seller">
        <p className="wh-onchain-warn">{text("seller.unavailable")}</p>
        {reasons}
        {data.refreshing ? (
          <p role="status">{text("levels.refreshing")}</p>
        ) : null}
      </div>
    );

  const time = data.last_at ? utcStamp(Date.parse(data.last_at)) : "";
  const late = data.data_state === "delayed" || data.data_state === "stale";
  return (
    <div className="wh-seller">
      <p className="wh-seller-meta">
        {text("seller.meta", { time: time || text("missing") })}
        {data.forming_at ? (
          // Once the data is late, the hour that was forming has closed since.
          <span> · {text(late ? "seller.formingOld" : "seller.forming")}</span>
        ) : null}
      </p>
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

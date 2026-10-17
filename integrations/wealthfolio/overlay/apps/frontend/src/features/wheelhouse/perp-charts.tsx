import {
  memo,
  useCallback,
  useId,
  useMemo,
  useState,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { useWheelhouseText, type TextFn } from "./i18n";
import type {
  PerpBlock,
  PerpState,
  PerpStatesView,
  PerpThresholds,
} from "./perps-contract";
import { sigUsd, usdPrice } from "./seller-charts";

type ChartKey = "c1" | "c2" | "c3" | "c4";
type PriceChart = "c1" | "c2";

const BUCKET = 600_000;
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const BLOCK_MS: Record<PerpStatesView["window"], number> = {
  "4h": 4 * HOUR,
  "8h": 8 * HOUR,
};
const HEIGHT: Record<ChartKey, number> = { c1: 210, c2: 170, c3: 180, c4: 210 };
// The states each price chart shades, in the original's legend order; chop is never shaded.
const SHADED: Record<PriceChart, readonly PerpState[]> = {
  c1: ["longsq", "shortsq", "longun", "shortun"],
  c2: ["longbd", "shortbd", "spot"],
};
const SQUEEZES: readonly PerpState[] = ["shortsq", "longsq"];
const NONE: readonly PerpState[] = [];
// Under O6 a threshold is null while its sample has fewer blocks than seven days' worth.
const REFERENCE_BLOCKS: Record<PerpStatesView["window"], number> = {
  "4h": 42,
  "8h": 21,
};

// One drawn block of the view; `block` is null for the tail short of half a block, which is
// drawn but never judged. The tail carries no coverage, so its delta and liquidations are left
// out: a partly collected sum would read as a whole one.
interface Item {
  at: string;
  t0: number;
  // The start of its last bucket: lines put the block's close there.
  t1: number;
  block: PerpBlock | null;
  price: number | null;
  oi: number | null;
  delta: number | null;
  sliq: number | null;
  lliq: number | null;
}

const round = (value: number) => Math.round(value * 100) / 100;
const isNumber = (value: number | null): value is number => value != null;
const utcMinute = (t: number) =>
  new Date(t).toISOString().slice(0, 16).replace("T", " ");
const utcClock = (t: number) => new Date(t).toISOString().slice(11, 16);
const utcDay = (t: number) => new Date(t).toISOString().slice(5, 10);
// Three significant digits with an SI suffix, the way the original prints BTC amounts.
const sig = (value: number) => sigUsd(value).replace("$", "");
// Axis labels read a plain 0 at the zero line.
const tick = (value: number) => (value === 0 ? "0" : sig(value));
const btc = (value: number | null) =>
  value == null ? "—" : `${sig(value)} BTC`;
const money = (value: number | null) => (value == null ? "—" : usdPrice(value));

// Thresholds in the units the rules compare them in: liquidations and OI change in BTC, price
// change in percent. One whose sample was too short to rank is null and reads "—".
function thresholdValues(text: TextFn, thresholds: PerpThresholds) {
  return [
    { label: text("perp.thresholds.sLiq"), value: btc(thresholds.s_liq) },
    { label: text("perp.thresholds.lLiq"), value: btc(thresholds.l_liq) },
    { label: text("perp.thresholds.oi"), value: btc(thresholds.oi) },
    {
      label: text("perp.thresholds.px"),
      value: thresholds.px == null ? "—" : `${thresholds.px.toFixed(2)}%`,
    },
  ];
}
export const thresholdsText = (text: TextFn, thresholds: PerpThresholds) =>
  thresholdValues(text, thresholds)
    .map(({ label, value }) => `${label} ${value}`)
    .join(" · ");

// The blocks reaching into the view, including one across its left edge, then the tail.
function itemsOf(view: PerpStatesView, from: number, size: number): Item[] {
  const items: Item[] = view.blocks.map((block) => ({
    at: block.t0,
    t0: Date.parse(block.t0),
    t1: Date.parse(block.t1),
    block,
    price: block.price_close,
    oi: block.oi_close,
    delta: block.delta_sum,
    sliq: block.sliq_sum,
    lliq: block.lliq_sum,
  }));
  const tail = view.tail;
  if (tail)
    items.push({
      at: tail.t0,
      t0: Date.parse(tail.t0),
      t1: Date.parse(tail.t1),
      block: null,
      price: tail.price_close,
      oi: tail.oi_close,
      delta: null,
      sliq: null,
      lliq: null,
    });
  return items.filter((item) => item.t0 + size > from);
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

// The x axis runs from the view's start to the last closed bucket, as the original's does.
function frame(width: number, height: number, from: number, last: number) {
  const compact = width < 500;
  const left = compact ? 40 : 52;
  const right = compact ? 44 : 52;
  const top = 10;
  const plotW = Math.max(40, width - left - right);
  const plotH = height - top - 24;
  const span = Math.max(1, last - from);
  const x = (t: number) => left + ((t - from) / span) * plotW;
  return {
    left,
    top,
    plotW,
    plotH,
    span,
    x,
    // Bands and the cursor are cut at the plot's edges.
    xc: (t: number) => Math.min(left + plotW, Math.max(left, x(t))),
  };
}

// A linear scale over the values, padded by 8% as the original pads its extents.
function linear(values: number[], top: number, height: number) {
  if (!values.length) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.01 || 1;
  const min = lo - pad;
  const max = hi + pad;
  return {
    min,
    max,
    y: (v: number) => top + height * (1 - (v - min) / (max - min)),
  };
}

// Symmetric about zero: `mid` is where zero sits and `half` the height up to the largest value.
// Without values there is no scale, so no axis is drawn.
function symmetric(values: number[], mid: number, half: number) {
  if (!values.length) return null;
  const max = Math.max(...values.map(Math.abs)) || 1;
  return { max, y: (v: number) => mid - (v / max) * half };
}

// Consecutive blocks with a value are joined; a block without one breaks the line, and a lone
// point is drawn as a dot.
function linePath(
  items: Item[],
  value: (item: Item) => number | null,
  x: (t: number) => number,
  y: (v: number) => number,
) {
  const runs: string[][] = [];
  let run: string[] | null = null;
  for (const item of items) {
    const v = value(item);
    if (v == null) {
      run = null;
      continue;
    }
    if (!run) {
      run = [];
      runs.push(run);
    }
    run.push(`${round(x(item.t1))},${round(y(v))}`);
  }
  return runs
    .map((points) =>
      points.length === 1
        ? `M${points[0]}L${points[0]}`
        : `M${points.join("L")}`,
    )
    .join("");
}

interface LayerProps {
  chart: ChartKey;
  items: Item[];
  from: number;
  last: number;
  size: number;
  hidden: readonly PerpState[];
  uid: string;
  bandLabel: string;
  width: number;
  height: number;
}

// The part of a chart that does not change with the reading; memoized so moving the reading does
// not redraw every block.
const Layer = memo(function Layer({
  chart,
  items,
  from,
  last,
  size,
  hidden,
  uid,
  bandLabel,
  width,
  height,
}: LayerProps) {
  const f = frame(width, height, from, last);
  const hatch = `url(#${uid}-hatch)`;
  const blockSpan = (item: Item) => {
    const x0 = f.xc(item.t0);
    return {
      x: round(x0),
      width: round(Math.max(1, f.xc(item.t0 + size) - x0)),
    };
  };
  const axis = (
    side: "left" | "right",
    ticks: number[],
    y: (v: number) => number,
    label: (v: number) => string,
  ) => (
    <g key={side}>
      {ticks.map((v) => (
        <g key={v}>
          {side === "left" ? (
            <line
              className="wh-perp-grid"
              x1={f.left}
              x2={f.left + f.plotW}
              y1={round(y(v))}
              y2={round(y(v))}
            />
          ) : null}
          <text
            className={`wh-perp-tick wh-perp-tick--${side}`}
            x={side === "left" ? f.left - 6 : f.left + f.plotW + 6}
            y={round(y(v) + 3.5)}
            textAnchor={side === "left" ? "end" : "start"}
          >
            {label(v)}
          </text>
        </g>
      ))}
    </g>
  );
  const price = linear(
    items.map((item) => item.price).filter(isNumber),
    f.top,
    f.plotH,
  );
  const pricePath = price ? (
    <path
      key="price"
      className="wh-perp-price"
      d={linePath(items, (item) => item.price, f.x, price.y)}
    />
  ) : null;
  const axes: ReactNode[] = [];
  // Bands, bars and hatching are cut at the plot's edges; lines end inside it on their own.
  const clipped: ReactNode[] = [];
  const lines: ReactNode[] = [];

  if (chart === "c1" || chart === "c2") {
    const shaded = SHADED[chart].filter((state) => !hidden.includes(state));
    for (const item of items) {
      const block = item.block;
      if (!block) continue;
      if (!block.covered)
        clipped.push(
          <rect
            key={item.at}
            className="wh-perp-uncovered"
            data-uncovered="block"
            data-t0={item.at}
            {...blockSpan(item)}
            y={f.top}
            height={f.plotH}
            fill={hatch}
          />,
        );
      else if (block.state && shaded.includes(block.state))
        clipped.push(
          <rect
            key={item.at}
            className={`wh-perp-band wh-perp-band--${block.state}`}
            data-state={block.state}
            data-t0={item.at}
            {...blockSpan(item)}
            y={f.top}
            height={f.plotH}
          />,
        );
    }
    if (price)
      axes.push(
        axis("left", niceTicks(price.min, price.max, 4), price.y, sigUsd),
      );
    lines.push(pricePath);
  }

  if (chart === "c3") {
    const oi = linear(
      items.map((item) => item.oi).filter(isNumber),
      f.top,
      f.plotH,
    );
    if (oi) {
      axes.push(axis("left", niceTicks(oi.min, oi.max, 4), oi.y, sig));
      lines.push(
        <path
          key="oi"
          className="wh-perp-oi"
          d={linePath(items, (item) => item.oi, f.x, oi.y)}
        />,
      );
    }
    if (price)
      axes.push(
        axis("right", niceTicks(price.min, price.max, 4), price.y, sigUsd),
      );
    lines.push(pricePath);
  }

  if (chart === "c4") {
    // Delta above and the liquidations in a band beneath, split the way the original splits it.
    const deltaH = f.plotH * 0.56;
    const bandTop = f.top + f.plotH * 0.65;
    const bandH = f.top + f.plotH - bandTop;
    const deltaShown = (item: Item) => !item.block || item.block.delta_covered;
    const liqShown = (item: Item) => !item.block || item.block.liq_covered;
    const delta = symmetric(
      items
        .filter(deltaShown)
        .map((item) => item.delta)
        .filter(isNumber),
      f.top + deltaH / 2,
      deltaH / 2,
    );
    const liq = symmetric(
      items
        .filter(liqShown)
        .flatMap((item) => [item.sliq, item.lliq])
        .filter(isNumber),
      bandTop + bandH / 2,
      bandH / 2,
    );
    // Bars sit on the block's nominal centre, 85% of a block wide.
    const barW = Math.max(1, (size / f.span) * f.plotW * 0.85);
    const barX = (item: Item) => round(f.x(item.t0 + size / 2) - barW / 2);
    const bar = (item: Item, kind: string, y0: number, y1: number) => (
      <rect
        key={`${kind}${item.at}`}
        className={`wh-perp-bar wh-perp-bar--${kind}`}
        data-t0={item.at}
        x={barX(item)}
        y={round(Math.min(y0, y1))}
        width={round(barW)}
        height={round(Math.abs(y1 - y0))}
      />
    );
    const missing = (item: Item, kind: string, y: number, h: number) => (
      <rect
        key={`${kind}${item.at}`}
        className="wh-perp-uncovered"
        data-uncovered={kind}
        data-t0={item.at}
        x={barX(item)}
        y={round(y)}
        width={round(barW)}
        height={round(h)}
        fill={hatch}
      />
    );
    clipped.push(
      <rect
        key="band"
        className="wh-perp-liqband"
        x={f.left}
        y={round(bandTop)}
        width={round(f.plotW)}
        height={round(bandH)}
      />,
    );
    for (const item of items) {
      if (!deltaShown(item))
        clipped.push(missing(item, "delta", f.top, deltaH));
      else if (delta && item.delta)
        clipped.push(
          bar(
            item,
            item.delta > 0 ? "buy" : "sell",
            delta.y(0),
            delta.y(item.delta),
          ),
        );
      if (!liqShown(item)) clipped.push(missing(item, "liq", bandTop, bandH));
      else if (liq) {
        // Short liquidations are forced buying, drawn up; long ones forced selling, drawn down.
        if (item.sliq)
          clipped.push(bar(item, "short", liq.y(0), liq.y(item.sliq)));
        if (item.lliq)
          clipped.push(bar(item, "long", liq.y(0), liq.y(-item.lliq)));
      }
    }
    for (const scale of [delta, liq]) {
      if (!scale) continue;
      const y = scale.y(0);
      lines.push(
        <line
          key={`zero${y}`}
          className="wh-perp-zero"
          x1={f.left}
          x2={f.left + f.plotW}
          y1={round(y)}
          y2={round(y)}
        />,
      );
    }
    lines.push(
      <text
        key="band-label"
        className="wh-perp-bandlabel"
        x={f.left + 6}
        y={round(bandTop + 12)}
      >
        {bandLabel}
      </text>,
    );
    if (delta)
      axes.push(
        axis("left", niceTicks(-delta.max, delta.max, 4), delta.y, tick),
      );
    if (liq)
      axes.push(
        axis("right", niceTicks(-liq.max, liq.max, 3), liq.y, (v) =>
          tick(Math.abs(v)),
        ),
      );
  }

  return (
    <>
      <defs>
        <clipPath id={`${uid}-clip`}>
          <rect x={f.left} y={f.top} width={round(f.plotW)} height={f.plotH} />
        </clipPath>
        <pattern
          id={`${uid}-hatch`}
          patternUnits="userSpaceOnUse"
          width="6"
          height="6"
          patternTransform="rotate(45)"
        >
          <line className="wh-perp-hatch" x1="0" y1="0" x2="0" y2="6" />
        </pattern>
      </defs>
      {axes}
      {timeTicks(from, last, Math.max(2, Math.floor(f.plotW / 64))).map(
        ([t, label]) => (
          <text
            key={t}
            className="wh-perp-tick"
            x={round(f.x(t))}
            y={height - 8}
            textAnchor="middle"
          >
            {label}
          </text>
        ),
      )}
      <text className="wh-perp-tick" x="2" y={height - 8}>
        UTC
      </text>
      <g clipPath={`url(#${uid}-clip)`}>{clipped}</g>
      {lines}
    </>
  );
});

// Observes the svg whenever it mounts, also when it appears after a "no blocks" message.
function useChartWidth() {
  const [width, setWidth] = useState(720);
  const ref = useCallback((el: SVGSVGElement | null) => {
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

interface Reading {
  values: { label: string; value: string }[];
  notes: string[];
}

function Panel({
  chart,
  items,
  from,
  last,
  size,
  hidden,
  legend,
  read,
  past,
}: {
  chart: ChartKey;
  items: Item[];
  from: number;
  last: number;
  size: number;
  hidden: readonly PerpState[];
  legend: ReactNode;
  read: (item: Item) => Reading;
  // O6: each block's thresholds come from the 90 days before it alone.
  past: boolean;
}) {
  const { text } = useWheelhouseText();
  const uid = useId().replace(/[^\w-]/g, "");
  const [ref, width] = useChartWidth();
  // A reading belongs to the blocks it was taken on; new blocks start again from the latest.
  const [hover, setHover] = useState<{ items: Item[]; index: number } | null>(
    null,
  );
  const height = HEIGHT[chart];
  const f = frame(width, height, from, last);
  const index =
    hover && hover.items === items && hover.index < items.length
      ? hover.index
      : null;
  const item = items[index ?? items.length - 1];
  const show = (next: number | null) =>
    setHover(next == null ? null : { items, index: next });
  const at = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return;
    const px = ((event.clientX - box.left) / box.width) * width;
    const t = from + ((px - f.left) / f.plotW) * f.span;
    let k = 0;
    while (k + 1 < items.length && items[k + 1].t0 <= t) k += 1;
    show(k);
  };
  const key = (event: KeyboardEvent<SVGSVGElement>) => {
    const end = items.length - 1;
    const current = index ?? end;
    const next: Record<string, number | null> = {
      ArrowLeft: Math.max(0, current - 1),
      ArrowRight: Math.min(end, current + 1),
      Home: 0,
      End: null,
      Escape: null,
    };
    if (!(event.key in next)) return;
    event.preventDefault();
    show(next[event.key]);
  };
  const title = text(`perp.${chart}.title`);
  // A block spans its full length; the tail ends with its last bucket.
  const span = item
    ? `${utcMinute(item.t0)} → ${utcClock(item.block ? item.t0 + size : item.t1 + BUCKET)}`
    : "";
  const reading = item ? read(item) : null;

  return (
    <section
      className="wh-perp-panel"
      data-chart={chart}
      aria-labelledby={`${uid}-title`}
    >
      <h3 id={`${uid}-title`}>{title}</h3>
      {item && reading ? (
        <>
          <svg
            ref={ref}
            className="wh-perp-svg"
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={text("perp.chart.aria", { title })}
            tabIndex={0}
            onPointerMove={at}
            onPointerDown={at}
            // A finger lifting also leaves; only a mouse that moves away clears the reading.
            onPointerLeave={(event) => {
              if (event.pointerType === "mouse") show(null);
            }}
            onKeyDown={key}
            onBlur={() => show(null)}
          >
            <Layer
              chart={chart}
              items={items}
              from={from}
              last={last}
              size={size}
              hidden={hidden}
              uid={uid}
              bandLabel={text("perp.chart.liquidations")}
              width={width}
              height={height}
            />
            {index != null ? (
              <rect
                className="wh-perp-cursor"
                x={round(f.xc(item.t0))}
                y={f.top}
                width={round(Math.max(1, f.xc(item.t0 + size) - f.xc(item.t0)))}
                height={f.plotH}
              />
            ) : null}
          </svg>
          <div className="wh-perp-legend">{legend}</div>
          <p className="wh-perp-reading" aria-live="polite">
            <span className="wh-perp-when">
              {index == null
                ? text("perp.chart.latest", { span })
                : `${span} UTC`}
            </span>
            {reading.values.map((value) => (
              <span key={value.label}>
                {value.label} <b>{value.value}</b>
              </span>
            ))}
            {reading.notes.length ? (
              <span className="wh-perp-notes">{reading.notes.join(" · ")}</span>
            ) : null}
          </p>
        </>
      ) : (
        <p className="wh-muted">{text("perp.chart.noData")}</p>
      )}
      <div className="wh-perp-read">
        {(["shows", "implies", "how"] as const).map((part) => (
          <div key={part}>
            <h4>{text(`seller.read.${part}`)}</h4>
            <p>
              {text(
                chart === "c1" && part === "how" && past
                  ? "perp.c1.howPast"
                  : `perp.${chart}.${part}`,
              )}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

// Charts 1–4 for the view and Show: the payload's blocks folded to one point each. While
// collecting with nothing judged, only Charts 3 and 4 are drawn; under O6 earlier blocks can be
// judged while the view collects, and then Charts 1 and 2 show them.
export function PerpCharts({
  view,
  show,
  verified,
}: {
  view: PerpStatesView;
  show: number;
  verified: boolean;
}) {
  const { text } = useWheelhouseText();
  const [hidden, setHidden] = useState<
    Record<PriceChart, readonly PerpState[]>
  >({ c1: NONE, c2: NONE });
  const table = view.tables.find((item) => item.show_days === show);
  const size = BLOCK_MS[view.window];
  const from = table ? Date.parse(table.view_from) : Number.NaN;
  const last = view.last ? Date.parse(view.last) : Number.NaN;
  const items = useMemo(
    () => (Number.isNaN(from) ? [] : itemsOf(view, from, size)),
    [view, from, size],
  );
  if (Number.isNaN(from) || Number.isNaN(last)) return null;

  const label = (state: PerpState) =>
    SQUEEZES.includes(state) && !verified
      ? text("perp.unverified", { state: text(`perp.state.${state}`) })
      : text(`perp.state.${state}`);
  const o1 = view.rules.includes("O1");
  const o6 = view.rules.includes("O6");
  const thresholds = view.thresholds;
  // Under O6 a squeeze also needs liquidations on its side, so a zero threshold no longer turns
  // every large move into one.
  const zeroThreshold =
    !o6 &&
    thresholds != null &&
    (thresholds.s_liq === 0 || thresholds.l_liq === 0);
  // Why a covered block was not judged, from its own fields: O1 leaves the forming block out;
  // O6 leaves out blocks with imputed inputs or a null threshold, too few blocks before them.
  const unjudged = (block: PerpBlock) => {
    const why: string[] = [];
    if (o1 && block.forming) why.push(text("perp.chart.why.forming"));
    const imputed =
      block.imputed.dpx || block.imputed.doi || block.imputed.sums;
    if (o6 && imputed) why.push(text("perp.chart.why.imputed"));
    const own = block.thresholds;
    if (own && [own.s_liq, own.l_liq, own.oi, own.px].includes(null))
      why.push(
        text("perp.chart.why.reference", {
          count: REFERENCE_BLOCKS[view.window],
        }),
      );
    return why;
  };
  // Notes on what decided a judged block; an unjudged one was decided by nothing. Charts 1 and 2
  // (`judging`) say in the block's value that O1 left a covered forming block unjudged.
  const notes = (item: Item, judging = false) => {
    const block = item.block;
    const out: string[] = [];
    if (block?.forming && !(judging && o1 && block.covered))
      out.push(text("perp.chart.forming"));
    if (!block?.state) return out;
    const imputed = (["dpx", "doi", "sums"] as const)
      .filter((part) => block.imputed[part])
      .map((part) => text(`perp.chart.imputed.${part}`));
    if (imputed.length)
      out.push(text("perp.chart.imputed", { list: imputed.join(", ") }));
    if (zeroThreshold) out.push(text("perp.chart.zeroThreshold"));
    return out;
  };
  const uncovered = text("perp.chart.uncovered");
  const priceValue = (item: Item) => ({
    label: text("perp.chart.price"),
    value: money(item.price),
  });
  const stateValue = (item: Item) => {
    const block = item.block;
    if (!block) return text("perp.chart.partial");
    if (!block.covered) return uncovered;
    if (block.state) return label(block.state);
    const why = unjudged(block);
    return why.length
      ? text("perp.chart.notJudgedWhy", { list: why.join(", ") })
      : text("perp.chart.notJudged");
  };
  // O6: the block's own thresholds, which it was or would have been judged against; one reading
  // item each, so that they wrap on a narrow screen.
  const ownThresholds = (item: Item) =>
    item.block?.thresholds
      ? thresholdValues(text, item.block.thresholds).map(
          ({ label, value }) => ({
            label: text("perp.chart.threshold", { name: label }),
            value,
          }),
        )
      : [];
  const key = (tone: string, name: string) => (
    <span key={tone}>
      <i
        className={`wh-perp-swatch wh-perp-swatch--${tone}`}
        aria-hidden="true"
      />
      {name}
    </span>
  );
  const priceKey = key("price", text("perp.chart.price"));

  // Legend counts: blocks whose nominal centre lies in [from, last], the original's rule (Table 1
  // counts by the buckets' centre instead). n is the judged ones; uncovered ones are counted apart.
  const centred = items.flatMap((item) => {
    const centre = item.t0 + size / 2;
    return item.block && centre >= from && centre <= last ? [item.block] : [];
  });
  const judged = centred.filter((block) => block.state != null);
  const uncoveredCount = centred.filter((block) => !block.covered).length;
  const notJudgedCount = centred.filter(
    (block) => block.covered && block.state == null,
  ).length;
  const stateLegend = (chart: PriceChart) => (
    <>
      {SHADED[chart].map((state) => {
        const off = hidden[chart].includes(state);
        const count = judged.filter((block) => block.state === state).length;
        return (
          <button
            key={state}
            type="button"
            aria-pressed={!off}
            title={text("perp.chart.toggle")}
            onClick={() =>
              setHidden((current) => ({
                ...current,
                [chart]: off
                  ? current[chart].filter((item) => item !== state)
                  : [...current[chart], state],
              }))
            }
          >
            <i
              className={`wh-perp-swatch wh-perp-swatch--${state}`}
              aria-hidden="true"
            />
            {label(state)}{" "}
            <b>{judged.length ? `${count} / ${judged.length}` : "—"}</b>
          </button>
        );
      })}
      {uncoveredCount
        ? key(
            "uncovered",
            text("perp.chart.uncoveredCount", { count: uncoveredCount }),
          )
        : null}
      {notJudgedCount ? (
        <span key="notjudged">
          {text("perp.chart.notJudgedCount", { count: notJudgedCount })}
        </span>
      ) : null}
      {priceKey}
    </>
  );
  const c4Uncovered = items.some(
    (item) =>
      item.block && (!item.block.delta_covered || !item.block.liq_covered),
  );

  const anyJudged = view.blocks.some((block) => block.state != null);

  const charts: {
    chart: ChartKey;
    legend: ReactNode;
    read: (item: Item) => Reading;
  }[] = [
    ...(view.collecting && !anyJudged
      ? []
      : (["c1", "c2"] as const).map((chart) => ({
          chart,
          legend: stateLegend(chart),
          read: (item: Item) => ({
            values: [
              priceValue(item),
              { label: text("perp.chart.block"), value: stateValue(item) },
              ...ownThresholds(item),
            ],
            notes: notes(item, true),
          }),
        }))),
    {
      chart: "c3",
      legend: (
        <>
          {key("oi", text("perp.chart.oiKey"))}
          {priceKey}
        </>
      ),
      read: (item) => ({
        values: [
          { label: text("perp.chart.oi"), value: btc(item.oi) },
          priceValue(item),
        ],
        notes: notes(item),
      }),
    },
    {
      chart: "c4",
      legend: (
        <>
          {key("buy", text("perp.chart.buy"))}
          {key("sell", text("perp.chart.sell"))}
          {key("short", text("perp.chart.shortLiq"))}
          {key("long", text("perp.chart.longLiq"))}
          {c4Uncovered
            ? key("uncovered", text("perp.chart.uncoveredKey"))
            : null}
        </>
      ),
      read: (item) => {
        const liqMissing = item.block != null && !item.block.liq_covered;
        return {
          values: [
            {
              label: text("perp.chart.delta"),
              value:
                item.block && !item.block.delta_covered
                  ? uncovered
                  : btc(item.delta),
            },
            {
              label: text("perp.chart.shortLiq"),
              value: liqMissing ? uncovered : btc(item.sliq),
            },
            {
              label: text("perp.chart.longLiq"),
              value: liqMissing ? uncovered : btc(item.lliq),
            },
          ],
          notes: notes(item),
        };
      },
    },
  ];

  return (
    <>
      {charts.map(({ chart, legend, read }) => (
        <Panel
          key={chart}
          chart={chart}
          items={items}
          from={from}
          last={last}
          size={size}
          hidden={chart === "c1" || chart === "c2" ? hidden[chart] : NONE}
          legend={legend}
          read={read}
          past={o6}
        />
      ))}
    </>
  );
}

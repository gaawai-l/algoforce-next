import {
  memo,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { getCostFlow } from "./client";
import {
  DEFAULT_SIDE,
  fitSide,
  samplePDF,
  type SideCurves,
  type SideSetting,
} from "./cost-flow-engine";
import {
  ALL_ON,
  WINDOWS,
  YOUNG,
  ZOOMS3,
  ZOOMS4,
  afterZoom,
  ageLegend,
  ageRows,
  ageSegments,
  ageTip,
  ageWeights,
  agingNote,
  chip,
  clusterCells,
  clusterMeta,
  clusters,
  flowTip,
  flowTotals,
  fmtPrice,
  fmtSigned,
  gridFor,
  kLabel,
  labelX,
  legendRows,
  mixCells,
  mixRows,
  mixtureMeta,
  plotFrame,
  segments,
  sideWeights,
  toggle,
  udiff,
  type AgeRow,
  type Cluster,
  type FlowRow,
  type Found,
  type Holders,
  type Seg,
  type Side,
  type TableCells,
  type Toggles,
  type Window,
  type Zoom,
} from "./cost-flow";
import { useWheelhouseText, type MessageKey, type TextFn } from "./i18n";
import type { CostFlowView } from "./onchain-contract";
import { reasonText, rulesNote } from "./onchain-text";
import { useChartWidth } from "./seller-charts";
import { si, ticks } from "./sell-side";
import { Segments } from "./sell-side-charts";

// The Cost basis flow: Chart 3, Buy & Sell Side By Cost Basis, and under it Chart 4, its Age
// Breakdown, as on the original state-report page (A = raw/script_2_app.js, H =
// raw/state-report.html). The service sends the snapshots; the rows, the bars and the engines'
// curves are worked out here, each from its own inputs only.

const round = (value: number) => Math.round(value * 100) / 100;
const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
// "19 Oct 2026", or "19 Oct" without the year; days and instants are read in UTC.
const dayLabel = (iso: string | null, year = true) => {
  if (!iso) return null;
  const d = new Date(iso);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}${year ? ` ${d.getUTCFullYear()}` : ""}`;
};
const timeLabel = (iso: string | null) => (iso ? new Date(iso).toISOString().slice(11, 16) : null);

// "cohort_sum:lin500" and the like, the QC checks the worker found failing.
function qcText(text: TextFn, code: string) {
  const sum = /^cohort_sum:lin(\d+)$/.exec(code);
  if (sum) return text("costflow.qc.cohort_sum", { bucket: `$${sum[1]}` });
  const sold = /^sold_negative:(.+)$/.exec(code);
  if (sold) return text("costflow.qc.sold_negative", { window: sold[1] });
  if (code === "age_floor") return text("costflow.qc.age_floor");
  return code;
}

// The plot's height follows its width, like the original's 940x660, between 300 and 440 px.
const heightFor = (width: number) =>
  Math.round(Math.min(440, Math.max(300, (width * 660) / 940)));

// The row whose price is nearest `price`; prices run up.
function nearest(prices: readonly number[], price: number) {
  let lo = 0;
  let hi = prices.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (prices[mid] < price) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && price - prices[lo - 1] < prices[lo] - price ? lo - 1 : lo;
}

// One drawn bar, in BTC from x0 to x1 on its row; key names its group for isolating it.
interface FlowBar {
  row: number;
  x0: number;
  x1: number;
  className: string;
  key?: string;
}
// A curve as [BTC, price] points: negative BTC is drawn on the sell side.
interface FlowCurve {
  side: Side;
  kind: "kde" | "mix";
  points: [number, number][];
}
interface FlowMark {
  side: Side;
  btc: number;
  price: number;
  label: string;
  kind: "k" | "m";
}

interface LayerProps {
  prices: number[];
  yDomain: [number, number];
  mag: number;
  bars: FlowBar[];
  curves: FlowCurve[];
  marks: FlowMark[];
  spot: number;
  spotLabel: string;
  dim: string | null;
  width: number;
  height: number;
}

// Everything that does not move with the pointer; memoized so reading a bucket does not redraw
// the bars. A:1601-1665: BTC across, symmetric about zero; price up; the bars of a row stacked
// out from zero, the spot line dashed across, the curves and their K and M marks over them.
const Layer = memo(function Layer({
  prices,
  yDomain,
  mag,
  bars,
  curves,
  marks,
  spot,
  spotLabel,
  dim,
  width,
  height,
}: LayerProps) {
  const f = plotFrame(width);
  const plotH = height - f.top - f.bottom;
  const span = mag * 1.08;
  const x = (v: number) => f.left + ((v + span) / (2 * span)) * f.plotW;
  const [lo, hi] = yDomain;
  const y = (p: number) => f.top + (plotH * (hi - p)) / (hi - lo);
  const n = prices.length;
  const bh = Math.max(1, plotH / n - (n > 200 ? 0 : 1));
  const xTicks = ticks(-span, span, f.xTicks);
  const sy = y(spot);
  const path = (points: [number, number][]) =>
    points.map(([b, p], i) => `${i ? "L" : "M"}${round(x(b))},${round(y(p))}`).join("");
  return (
    <>
      {xTicks
        .filter((v) => v !== 0)
        .map((v) => (
          <line
            key={v}
            className="wh-seller-grid"
            x1={round(x(v))}
            x2={round(x(v))}
            y1={f.top}
            y2={f.top + plotH}
          />
        ))}
      {xTicks.map((v) => (
        <text
          key={v}
          className="wh-seller-tick wh-cf-tick--x"
          x={round(x(v))}
          y={f.top + plotH + 14}
          textAnchor="middle"
        >
          {v === 0 ? "0" : fmtSigned(v)}
        </text>
      ))}
      {ticks(lo, hi, f.yTicks).map((v) => (
        <text
          key={v}
          className="wh-seller-tick wh-cf-tick--y"
          x={f.left - 6}
          y={round(y(v) + 3.5)}
          textAnchor="end"
        >
          {`$${si(v)}`}
        </text>
      ))}
      <g>
        {bars.map((bar, i) => (
          <rect
            key={i}
            className={
              dim !== null && bar.key !== dim ? `${bar.className} wh-cf-dim` : bar.className
            }
            x={round(x(bar.x0))}
            y={round(y(prices[bar.row]) - bh / 2)}
            width={round(Math.max(0.5, x(bar.x1) - x(bar.x0)))}
            height={round(bh)}
          />
        ))}
      </g>
      <line
        className="wh-cf-zero"
        x1={round(x(0))}
        x2={round(x(0))}
        y1={f.top}
        y2={f.top + plotH}
      />
      {spot >= lo && spot <= hi ? (
        <>
          <line
            className="wh-cf-spotline"
            x1={f.left}
            x2={f.left + f.plotW}
            y1={round(sy)}
            y2={round(sy)}
          />
          <text className="wh-cf-spot" x={f.spotX} y={round(sy + 3.5)} textAnchor="end">
            {spotLabel}
          </text>
        </>
      ) : null}
      {curves.map((curve, i) => (
        <path
          key={i}
          className={`wh-cf-${curve.kind} wh-cf-${curve.kind}--${curve.side}`}
          d={path(curve.points)}
        />
      ))}
      {marks.map((mark, i) => {
        const px = x(mark.btc);
        const py = y(mark.price);
        return (
          <g key={i}>
            {mark.kind === "k" ? (
              <circle
                className={`wh-cf-dot wh-cf-dot--${mark.side}`}
                cx={round(px)}
                cy={round(py)}
                r={4}
              />
            ) : null}
            <text
              className={`wh-cf-label wh-cf-label--${mark.kind}-${mark.side}`}
              x={round(labelX(px, mark.side, f))}
              y={round(py + 3.5)}
              textAnchor={mark.side === "pos" ? "start" : "end"}
              fontSize={f.labelPx}
            >
              {mark.label}
            </text>
          </g>
        );
      })}
    </>
  );
});

// The rotated chart of Charts 3 and 4. The pointer or the arrow keys pick a row (onActive); the
// first arrow picks the row that holds spot, Home and End the ends, Escape none. captions are the
// sell side's and the buy side's, under the axis from left to right.
export function FlowPlot({
  prices,
  step,
  yDomain,
  mag,
  bars,
  curves,
  marks,
  spot,
  captions,
  label,
  dim,
  active,
  onActive,
}: {
  prices: number[];
  step: number;
  yDomain: [number, number];
  mag: number;
  bars: FlowBar[];
  curves: FlowCurve[];
  marks: FlowMark[];
  spot: number;
  captions: [string, string];
  label: string;
  dim: string | null;
  active: number | null;
  onActive: (row: number | null) => void;
}) {
  const { text } = useWheelhouseText();
  const [ref, width] = useChartWidth();
  const height = heightFor(width);
  const f = plotFrame(width);
  const plotH = height - f.top - f.bottom;
  const [lo, hi] = yDomain;
  const y = (p: number) => f.top + (plotH * (hi - p)) / (hi - lo);
  const n = prices.length;
  // The read bucket is marked across the plot over its own price range, at least 2 px high.
  const band = Math.max(2, (plotH * step) / (hi - lo));
  const at = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.height <= 0) return;
    const py = ((event.clientY - box.top) / box.height) * height;
    onActive(nearest(prices, hi - ((py - f.top) / plotH) * (hi - lo)));
  };
  const key = (event: KeyboardEvent<SVGSVGElement>) => {
    const last = n - 1;
    const start = nearest(prices, spot);
    const next: Record<string, number | null> = {
      ArrowUp: active === null ? start : Math.min(last, active + 1),
      ArrowDown: active === null ? start : Math.max(0, active - 1),
      Home: 0,
      End: last,
      Escape: null,
    };
    if (!(event.key in next)) return;
    event.preventDefault();
    onActive(next[event.key]);
  };
  return (
    <div className="wh-cf-plot">
      <svg
        ref={ref}
        className="wh-cf-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={label}
        tabIndex={0}
        data-rows={n}
        onPointerMove={at}
        onPointerDown={at}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse") onActive(null);
        }}
        onKeyDown={key}
        onBlur={() => onActive(null)}
      >
        <Layer
          prices={prices}
          yDomain={yDomain}
          mag={mag}
          bars={bars}
          curves={curves}
          marks={marks}
          spot={spot}
          spotLabel={text("costflow.axis.spot", { price: fmtPrice(spot) })}
          dim={dim}
          width={width}
          height={height}
        />
        {active !== null && active < n ? (
          <rect
            className="wh-cf-cursor"
            x={f.left}
            y={round(y(prices[active]) - band / 2)}
            width={f.plotW}
            height={round(band)}
          />
        ) : null}
      </svg>
      <div className="wh-cf-captions">
        <span>{captions[0]}</span>
        <span>{captions[1]}</span>
      </div>
    </div>
  );
}

// One side's KDE, peaks and mixture, fitted only when the rows, the weights or the side's
// setting change: hover, the readout and the chart's width never reach the engine. The setting is
// compared by its six values, so picking an option that is already on does not refit. Each fit is
// timed as "costflow-fit" (User Timing) for the browser check.
export function useSideCurves(
  rows: readonly { price: number }[],
  weights: readonly number[],
  setting: SideSetting,
): SideCurves | null {
  const { smoothing, bw, minProm, mixture, kMode, kManual } = setting;
  return useMemo(() => {
    performance.mark("costflow-fit-start");
    const curves = fitSide(
      rows.map((row) => row.price),
      weights,
      { smoothing, bw, minProm, mixture, kMode, kManual },
    );
    performance.measure("costflow-fit", "costflow-fit-start");
    performance.clearMarks("costflow-fit-start");
    return curves;
  }, [rows, weights, smoothing, bw, minProm, mixture, kMode, kManual]);
}

// A:1675-1746 without the engines: each side's KDE scaled to 92% of its tallest bar with a K mark
// on every peak, numbered as the Clusters table numbers it (U4), and its bells scaled together to
// 85%, each with an M mark at the row nearest its centre. Bells are sampled per row of `step`.
function drawCurves(
  prices: readonly number[],
  step: number,
  fits: readonly { side: Side; weights: readonly number[]; curves: SideCurves | null }[],
  cs: readonly Cluster[],
) {
  const curves: FlowCurve[] = [];
  const marks: FlowMark[] = [];
  for (const { side, weights, curves: fit } of fits) {
    if (!fit) continue;
    const sign = side === "pos" ? 1 : -1;
    const empPeak = Math.max(...weights);
    const sm = fit.sm;
    if (sm) {
      const natPeak = Math.max(...sm);
      const scale = natPeak > 0 && empPeak > 0 ? (empPeak * 0.92) / natPeak : 1;
      curves.push({ side, kind: "kde", points: prices.map((p, i) => [sm[i] * scale * sign, p]) });
      for (const peak of fit.peaks)
        marks.push({
          side,
          btc: sm[peak.index] * scale * sign,
          price: peak.location,
          label: `K${cs.find((c) => c.peak === peak)?.n}`,
          kind: "k",
        });
    }
    const mix = fit.mix;
    if (mix) {
      const per = mix.comps.map((c) => samplePDF(c, prices).map((v) => v * mix.totalW * step));
      let natPeak = 0;
      for (const sampled of per) for (const v of sampled) if (v > natPeak) natPeak = v;
      const scale = natPeak > 0 && empPeak > 0 ? (empPeak * 0.85) / natPeak : 1;
      per.forEach((sampled, j) => {
        curves.push({
          side,
          kind: "mix",
          points: prices.map((p, i) => [sampled[i] * scale * sign, p]),
        });
        let bi = 0;
        let bd = Infinity;
        prices.forEach((p, i) => {
          const d = Math.abs(p - mix.comps[j].mu);
          if (d < bd) {
            bd = d;
            bi = i;
          }
        });
        marks.push({
          side,
          btc: sampled[bi] * scale * sign,
          price: prices[bi],
          label: `M${j + 1}`,
          kind: "m",
        });
      });
    }
  }
  return { curves, marks };
}

const BAR_CLASS: Record<Seg["cls"], string> = {
  "bar-pos": "wh-cf-bar wh-cf-bar--pos",
  "bar-neg": "wh-cf-bar wh-cf-bar--neg",
  "bar-aging-pos": "wh-cf-bar wh-cf-bar--aging-pos",
  "bar-aging-neg": "wh-cf-bar wh-cf-bar--aging-neg",
};

// A:1592-1599 and A:1617-1633: each row's bars stacked out from zero, buys right and sells left,
// a bar of zero not drawn; mag is the widest stack on either side, not the net.
function stackBars(rows: readonly FlowRow[], h: Holders, aging: boolean) {
  const bars: FlowBar[] = [];
  let mag = 0;
  rows.forEach((r, row) => {
    let up = 0;
    let dn = 0;
    for (const sg of segments(r, h, aging)) {
      if (sg.v > 0) {
        bars.push({ row, x0: up, x1: up + sg.v, className: BAR_CLASS[sg.cls] });
        up += sg.v;
      } else if (sg.v < 0) {
        bars.push({ row, x0: dn + sg.v, x1: dn, className: BAR_CLASS[sg.cls] });
        dn += sg.v;
      }
    }
    mag = Math.max(mag, up, -dn);
  });
  return { bars, mag: mag || 1 };
}

// Chart 4's bars (A:3528-3536, A:3573-3612), stacked as Chart 3's: each shown bought group in its
// group's colour, then the sold bar in the colour of its row's band, drawn faint. Each bar keeps
// its legend key, so a hovered legend row can isolate it.
function stackAge(rows: readonly AgeRow[], t: Toggles) {
  const bars: FlowBar[] = [];
  let mag = 0;
  rows.forEach((r, row) => {
    let up = 0;
    let dn = 0;
    for (const sg of ageSegments(r, t)) {
      const className = `wh-cf-bar wh-cf-bar--${sg.sold ? "sold" : "bought"} wh-cf-age-${sg.band}`;
      if (sg.v > 0) {
        bars.push({ row, x0: up, x1: up + sg.v, className, key: sg.key });
        up += sg.v;
      } else if (sg.v < 0) {
        bars.push({ row, x0: dn + sg.v, x1: dn, className, key: sg.key });
        dn += sg.v;
      }
    }
    mag = Math.max(mag, up, -dn);
  });
  return { bars, mag: mag || 1 };
}

const SMOOTHINGS: readonly SideSetting["smoothing"][] = ["none", "auto", "kde"];
const SMOOTHING_NAMES = {
  none: "costflow.off",
  auto: "costflow.auto",
  kde: "costflow.manual",
} as const satisfies Record<SideSetting["smoothing"], MessageKey>;
const MIXTURES: readonly SideSetting["mixture"][] = ["none", "gmm"];
const K_OPTIONS: readonly ("auto" | number)[] = ["auto", 1, 2, 3, 4, 5];
type Fine = Partial<Pick<SideSetting, "bw" | "minProm">>;

// One side's smoothing, bells and k (H:830-918, A:1941-1975). The ⚙ chip opens the fine tuning:
// two sliders, live only with Manual smoothing. A slider shows its value at once and commits on
// the next animation frame, so a drag fits the side at most once a frame, with the last value.
export function SideControls({
  side,
  setting,
  curves,
  onSetting,
}: {
  side: Side;
  setting: SideSetting;
  curves: SideCurves | null;
  onSetting: (next: SideSetting) => void;
}) {
  const { text } = useWheelhouseText();
  const id = useId();
  const [open, setOpen] = useState(false);
  // The slider values shown while their commit waits for the frame.
  const [draft, setDraft] = useState<Fine>({});
  const pending = useRef<Fine>({});
  const frame = useRef<number | null>(null);
  // The frame commits onto the setting current when it runs.
  const latest = useRef({ setting, onSetting });
  useEffect(() => {
    latest.current = { setting, onSetting };
  });
  useEffect(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    },
    [],
  );
  const slide = (key: keyof Fine, value: number) => {
    setDraft((current) => ({ ...current, [key]: value }));
    pending.current = { ...pending.current, [key]: value };
    if (frame.current !== null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      const patch = pending.current;
      pending.current = {};
      setDraft({});
      latest.current.onSetting({ ...latest.current.setting, ...patch });
    });
  };
  const smooth = (smoothing: SideSetting["smoothing"]) => {
    if (smoothing === "kde") return onSetting({ ...setting, smoothing });
    // Leaving Manual drops a pending slider value and restores the defaults (A:1958).
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = null;
    pending.current = {};
    setDraft({});
    onSetting({ ...setting, smoothing, bw: DEFAULT_SIDE.bw, minProm: DEFAULT_SIDE.minProm });
  };
  const manual = setting.smoothing === "kde";
  const bw = draft.bw ?? setting.bw;
  const minProm = draft.minProm ?? setting.minProm;
  const fine = text(side === "neg" ? "costflow.fineSell" : "costflow.fineBuy");
  // H:863, H:868, A:1949-1953: the ranges and steps of the original; "auto" unless Manual.
  const sliders = [
    {
      key: "bw",
      label: "costflow.width",
      min: "0.005",
      max: "0.10",
      step: "0.001",
      value: bw,
      shown: bw.toFixed(3),
    },
    {
      key: "minProm",
      label: "costflow.cutoff",
      min: "0.01",
      max: "0.40",
      step: "0.005",
      value: minProm,
      shown: minProm.toFixed(2),
    },
  ] as const;
  return (
    <div className={`wh-cf-side wh-cf-side--${side}`} data-side={side}>
      <span className={`wh-cf-eyebrow wh-cf-eyebrow--${side}`}>
        {text(side === "neg" ? "costflow.eyebrow.sell" : "costflow.eyebrow.buy")}
      </span>
      <Segments
        label={text("costflow.smoothing")}
        options={SMOOTHINGS}
        value={setting.smoothing}
        name={(smoothing) => text(SMOOTHING_NAMES[smoothing])}
        onPick={smooth}
      />
      <Segments
        label={text("costflow.bells")}
        options={MIXTURES}
        value={setting.mixture}
        name={(mixture) => text(mixture === "gmm" ? "costflow.on" : "costflow.off")}
        onPick={(mixture) => onSetting({ ...setting, mixture })}
      />
      <Segments
        label={text("costflow.howMany")}
        options={K_OPTIONS}
        value={setting.kMode === "auto" ? "auto" : setting.kManual}
        name={(k) => (k === "auto" ? kLabel(text, setting, curves) : String(k))}
        onPick={(k) =>
          onSetting(
            k === "auto"
              ? { ...setting, kMode: "auto" }
              : { ...setting, kMode: "manual", kManual: k },
          )
        }
      />
      <button
        type="button"
        className="wh-cf-gear"
        aria-expanded={open}
        aria-label={`${fine} · ${chip(setting)}`}
        onClick={() => setOpen((current) => !current)}
      >
        ⚙ <span className="wh-cf-chip">{chip(setting)}</span>
      </button>
      {open ? (
        <div className="wh-cf-fine">
          <div className="wh-cf-fine-title">{fine}</div>
          {sliders.map((slider) => (
            <div key={slider.key} className="wh-cf-slider">
              <label htmlFor={`${id}-${slider.key}`}>{text(slider.label)}</label>
              <input
                id={`${id}-${slider.key}`}
                type="range"
                min={slider.min}
                max={slider.max}
                step={slider.step}
                value={slider.value}
                disabled={!manual}
                onChange={(event) => slide(slider.key, Number(event.target.value))}
              />
              <output htmlFor={`${id}-${slider.key}`}>
                {manual ? slider.shown : text("costflow.k.auto")}
              </output>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

const CLUSTER_COLS: readonly MessageKey[] = [
  "costflow.col.rank",
  "costflow.col.side",
  "costflow.col.price",
  "costflow.col.width",
  "costflow.col.btc",
  "costflow.col.share",
  "costflow.col.strength",
  "costflow.col.vsSpot",
];
const MIX_COLS: readonly MessageKey[] = [
  "costflow.col.m",
  "costflow.col.side",
  "costflow.col.centre",
  "costflow.col.spread",
  "costflow.col.share",
  "costflow.col.est",
  "costflow.col.vsSpot",
];

// A table of fitted levels (A:1819-1866): rank, side, the cells cost-flow.ts formats, and the
// vs-spot tag, support below spot and resistance above; without a spot the cell reads "—" untagged.
function FitTable({
  name,
  title,
  meta,
  head,
  rows,
  spot,
  empty,
}: {
  name: string;
  title: string;
  meta: string;
  head: readonly MessageKey[];
  rows: { rank: string; side: Side; cells: TableCells }[];
  spot: number;
  empty: string;
}) {
  const { text } = useWheelhouseText();
  return (
    <div className="wh-cf-fit" data-table={name}>
      <div className="wh-cf-fit-head">
        <h4>{title}</h4>
        <span className="wh-cf-fit-meta">{meta}</span>
      </div>
      <div className="wh-cf-table-wrap">
        <table className="wh-cf-table">
          <thead>
            <tr>
              {head.map((key) => (
                <th key={key} scope="col">
                  {text(key)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length ? (
              rows.map((row) => {
                const last = row.cells.cells.length - 1;
                const vs = row.cells.cells[last];
                return (
                  <tr key={`${row.side}-${row.rank}`}>
                    <th scope="row" className="wh-cf-rank">
                      {row.rank}
                    </th>
                    <td>
                      <span className="wh-cf-pill">
                        <i
                          className={`wh-cf-swatch wh-cf-swatch--${row.side}`}
                          aria-hidden="true"
                        />
                        {text(row.side === "pos" ? "costflow.buy" : "costflow.sell")}
                      </span>
                    </td>
                    {row.cells.cells.slice(0, last).map((cell, i) => (
                      <td key={i} className="wh-cf-num">
                        {cell}
                      </td>
                    ))}
                    <td>
                      {spot > 0 ? (
                        <span
                          className={`wh-cf-tag wh-cf-tag--${row.cells.below ? "support" : "resistance"}`}
                        >
                          {vs}
                        </span>
                      ) : (
                        vs
                      )}
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr>
                <td colSpan={head.length} className="wh-cf-empty">
                  {empty}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// The Clusters table (A:1819-1840): the peaks of both sides by price, K numbered in that order.
export function ClustersTable({
  rows,
  spot,
  empty,
}: {
  rows: Cluster[];
  spot: number;
  empty: string;
}) {
  const { text } = useWheelhouseText();
  return (
    <FitTable
      name="clusters"
      title={text("costflow.clustersTitle")}
      meta={clusterMeta(text, rows)}
      head={CLUSTER_COLS}
      rows={rows.map((c) => ({ rank: `K${c.n}`, side: c.side, cells: clusterCells(text, c, spot) }))}
      spot={spot}
      empty={empty}
    />
  );
}

// The three notes under a chart, always expanded.
export function ReadColumns({
  shows,
  implies,
  how,
}: {
  shows: MessageKey;
  implies: MessageKey;
  how: MessageKey;
}) {
  const { text } = useWheelhouseText();
  return (
    <div className="wh-seller-read">
      {(
        [
          ["seller.read.shows", shows],
          ["seller.read.implies", implies],
          ["seller.read.how", how],
        ] as const
      ).map(([heading, body]) => (
        <div key={heading}>
          <h4>{text(heading)}</h4>
          <p>{text(body)}</p>
        </div>
      ))}
    </div>
  );
}

// Window and Zoom belong to both charts (A:1919, U_SHARED); the rest of each chart's controls are
// its own.
interface Shared {
  window: Window;
  zoom: Zoom;
}
const SHARED: Shared = { window: "30d", zoom: 0 };
const HOLDERS: readonly Holders[] = ["all", "sth", "lth"];
const AGING = ["show", "hide"] as const;
const NO_ROWS: FlowRow[] = [];
const NO_AGE: AgeRow[] = [];
// Chart 4 reads the $500 grid only.
const AGE_STEP = 500;

// The bucket a chart reads, by its index in the rows it was read on. Rows from a refresh, or from
// any other change, can hold another bucket at that index, so the reading holds only while its
// rows are the ones drawn.
interface Reading {
  rows: readonly unknown[];
  row: number;
}

// The window's span: from the then day's close to D, at the snapshot's time while D is forming.
function WindowSpan({ view, w, then }: { view: CostFlowView; w: Window; then: string }) {
  const { text } = useWheelhouseText();
  return (
    <p className="wh-cf-span">
      {view.forming_at
        ? text("costflow.spanForming", {
            window: w,
            then: dayLabel(then, false) ?? "",
            day: dayLabel(view.now_day, false) ?? text("missing"),
            time: timeLabel(view.snapshot_at) ?? text("missing"),
          })
        : text("costflow.spanClosed", {
            window: w,
            then: dayLabel(then, false) ?? "",
            day: dayLabel(view.now_day, false) ?? text("missing"),
          })}
    </p>
  );
}

function Chart3({
  view,
  shared,
  onShared,
  active,
  onActive,
}: {
  view: CostFlowView;
  shared: Shared;
  onShared: (next: Partial<Shared>) => void;
  active: Reading | null;
  onActive: (next: Reading | null) => void;
}) {
  const { text } = useWheelhouseText();
  const [holders, setHolders] = useState<Holders>("all");
  const [aging, setAging] = useState(false);
  const [sides, setSides] = useState<Record<Side, SideSetting>>({
    pos: DEFAULT_SIDE,
    neg: DEFAULT_SIDE,
  });
  // A:1302: STH reads the $200 grid, as gridFor does.
  const step = holders === "sth" ? 200 : 500;
  // The rows the reader picked, with the then day and spot they were taken against.
  const picked = useMemo((): Found<{ rows: FlowRow[]; then: string; spot: number }> => {
    const grid = gridFor(view, holders);
    if (!grid || view.spot === null) return { ok: false, missing: "grid" };
    const found = udiff(grid, shared.window, holders, aging, shared.zoom, view.spot);
    if (!found.ok) return found;
    const then = grid.windows.find((item) => item.window === shared.window)!.then_day;
    return { ok: true, value: { rows: found.value, then, spot: view.spot } };
  }, [view, shared.window, shared.zoom, holders, aging]);
  const rows = picked.ok ? picked.value.rows : NO_ROWS;
  const posW = useMemo(() => sideWeights(rows, holders, aging, "pos"), [rows, holders, aging]);
  const negW = useMemo(() => sideWeights(rows, holders, aging, "neg"), [rows, holders, aging]);
  const pos = useSideCurves(rows, posW, sides.pos);
  const neg = useSideCurves(rows, negW, sides.neg);
  const cs = useMemo(() => clusters(pos, neg), [pos, neg]);
  const totals = useMemo(() => flowTotals(rows, holders, aging), [rows, holders, aging]);
  // A:1601-1614: Zoom All pads the occupied rows by 5% at each end, never below 0; a ±% zoom is
  // the stated band and gets none.
  const plot = useMemo(() => {
    if (!rows.length) return null;
    const prices = rows.map((row) => row.price);
    const lo0 = rows[0].price - step / 2;
    const hi0 = rows[rows.length - 1].price + step / 2;
    const pad = shared.zoom === 0 ? (hi0 - lo0) * 0.05 : 0;
    const yDomain: [number, number] = [Math.max(0, lo0 - pad), hi0 + pad];
    return { prices, yDomain, ...stackBars(rows, holders, aging) };
  }, [rows, holders, aging, step, shared.zoom]);
  const drawn = useMemo(
    () =>
      plot
        ? drawCurves(
            plot.prices,
            step,
            [
              { side: "pos", weights: posW, curves: pos },
              { side: "neg", weights: negW, curves: neg },
            ],
            cs,
          )
        : null,
    [plot, step, posW, negW, pos, neg, cs],
  );
  const title = text("costflow.c3.title");
  const reading = active !== null && active.rows === rows ? active.row : null;
  const read = (row: number | null) => onActive(row === null ? null : { rows, row });
  const own = (change: () => void) => {
    onActive(null);
    change();
  };

  return (
    <section
      className="wh-seller-panel"
      data-chart="costflow-3"
      aria-labelledby="wh-costflow-3"
    >
      <div className="wh-seller-head">
        <h3 id="wh-costflow-3">{title}</h3>
      </div>
      <div className="wh-ss-controls">
        <Segments
          label={text("costflow.window")}
          options={WINDOWS}
          value={shared.window}
          name={(w) => w}
          onPick={(w) => onShared({ window: w })}
        />
        <Segments
          label={text("costflow.holders")}
          options={HOLDERS}
          value={holders}
          name={(h) => (h === "all" ? text("costflow.all") : h.toUpperCase())}
          onPick={(h) => own(() => setHolders(h))}
        />
        <Segments
          label={text("costflow.zoom")}
          options={ZOOMS3}
          value={shared.zoom}
          name={(z) => (z === 0 ? text("costflow.all") : `±${z}%`)}
          onPick={(z) => onShared({ zoom: z })}
        />
      </div>
      {picked.ok && plot && drawn ? (
        <>
          <WindowSpan view={view} w={shared.window} then={picked.value.then} />
          <FlowPlot
            prices={plot.prices}
            step={step}
            yDomain={plot.yDomain}
            mag={plot.mag}
            bars={plot.bars}
            curves={drawn.curves}
            marks={drawn.marks}
            spot={picked.value.spot}
            captions={[text("costflow.axis.sell"), text("costflow.axis.buy")]}
            label={title}
            dim={null}
            active={reading}
            onActive={read}
          />
          <div className="wh-seller-legend wh-cf-legend">
            {legendRows(text, totals, holders).map((row) => (
              <span key={row.key} className="wh-seller-key">
                <i
                  className={`wh-seller-swatch wh-cf-swatch--${row.side}${row.key === "aging" ? " wh-cf-swatch--hollow" : ""}`}
                  aria-hidden="true"
                />
                {row.label} <b>{row.value}</b>
              </span>
            ))}
          </div>
          <div className="wh-cf-aging">
            <Segments
              label={text("costflow.aging")}
              options={AGING}
              value={aging ? "show" : "hide"}
              name={(option) => text(option === "show" ? "costflow.show" : "costflow.hide")}
              onPick={(option) => own(() => setAging(option === "show"))}
            />
            <span className="wh-cf-note">{agingNote(text, holders, aging, step)}</span>
          </div>
          <div className="wh-cf-sides">
            {(["neg", "pos"] as const).map((which) => (
              <SideControls
                key={which}
                side={which}
                setting={sides[which]}
                curves={which === "pos" ? pos : neg}
                onSetting={(next) => setSides((current) => ({ ...current, [which]: next }))}
              />
            ))}
          </div>
          <div className="wh-cf-readout" aria-live="polite">
            {reading !== null
              ? flowTip(text, rows[reading], step, shared.window).map((line, i) => (
                  <p key={i}>{line}</p>
                ))
              : null}
          </div>
          <div className="wh-cf-tables">
            <ClustersTable rows={cs} spot={picked.value.spot} empty={text("costflow.noClusters")} />
            <FitTable
              name="components"
              title={text("costflow.componentsTitle")}
              meta={mixtureMeta(text, pos, neg)}
              head={MIX_COLS}
              rows={mixRows(pos, neg).map((row) => ({
                rank: `M${row.m}`,
                side: row.side,
                cells: mixCells(text, row, picked.value.spot),
              }))}
              spot={picked.value.spot}
              empty={text("costflow.bellsOff")}
            />
          </div>
        </>
      ) : (
        <p className="wh-onchain-warn">
          {!picked.ok && picked.missing === "window"
            ? text("costflow.noWindow", { window: shared.window })
            : text("costflow.noGrid", {
                holders: holders === "all" ? text("costflow.all") : holders.toUpperCase(),
                step,
              })}
        </p>
      )}
      <ReadColumns shows="costflow.c3.shows" implies="costflow.c3.implies" how="costflow.c3.how" />
    </section>
  );
}

// Chart 4, the Age Breakdown (A:3460-3845): Chart 3's window and zoom on the $500 grid, the bought
// side split exactly by age group and the sold side coloured by the band of when price last traded
// at the level. The legend's rows hide their bars and isolate them on hover or focus; hiding one
// refits this chart's two sides only, and isolating one reads only what is already drawn.
function Chart4({
  view,
  shared,
  onShared,
  toggles,
  onToggles,
  dim,
  onDim,
  active,
  onActive,
}: {
  view: CostFlowView;
  shared: Shared;
  onShared: (next: Partial<Shared>) => void;
  toggles: Toggles;
  onToggles: (next: Toggles) => void;
  dim: string | null;
  onDim: (key: string | null) => void;
  active: Reading | null;
  onActive: (next: Reading | null) => void;
}) {
  const { text } = useWheelhouseText();
  const [sides, setSides] = useState<Record<Side, SideSetting>>({
    pos: DEFAULT_SIDE,
    neg: DEFAULT_SIDE,
  });
  // The rows of the shared window and zoom, with the then day and spot they were taken against.
  const picked = useMemo((): Found<{ rows: AgeRow[]; then: string; spot: number }> => {
    const found = ageRows(view, shared.window, shared.zoom);
    if (!found.ok) return found;
    const grid = gridFor(view, "all")!;
    const then = grid.windows.find((item) => item.window === shared.window)!.then_day;
    return { ok: true, value: { rows: found.value, then, spot: view.spot! } };
  }, [view, shared.window, shared.zoom]);
  const rows = picked.ok ? picked.value.rows : NO_AGE;
  const posW = useMemo(() => ageWeights(rows, toggles, "pos"), [rows, toggles]);
  const negW = useMemo(() => ageWeights(rows, toggles, "neg"), [rows, toggles]);
  const pos = useSideCurves(rows, posW, sides.pos);
  const neg = useSideCurves(rows, negW, sides.neg);
  const cs = useMemo(() => clusters(pos, neg), [pos, neg]);
  // A:3581-3584: the price axis spans the rows exactly, at any zoom.
  const plot = useMemo(() => {
    if (!rows.length) return null;
    const prices = rows.map((row) => row.price);
    const yDomain: [number, number] = [
      rows[0].price - AGE_STEP / 2,
      rows[rows.length - 1].price + AGE_STEP / 2,
    ];
    return { prices, yDomain, ...stackAge(rows, toggles) };
  }, [rows, toggles]);
  const drawn = useMemo(
    () =>
      plot
        ? drawCurves(
            plot.prices,
            AGE_STEP,
            [
              { side: "pos", weights: posW, curves: pos },
              { side: "neg", weights: negW, curves: neg },
            ],
            cs,
          )
        : null,
    [plot, posW, negW, pos, neg, cs],
  );
  const legend = ageLegend(text, rows, YOUNG[shared.window], toggles, shared.zoom);
  const title = text("costflow.c4.title");
  const reading = active !== null && active.rows === rows ? active.row : null;
  const read = (row: number | null) => onActive(row === null ? null : { rows, row });
  // A:3743-3751: a click flips the row, unless it is the last one shown, and ends the isolation.
  const flip = (key: string) => {
    onDim(null);
    onToggles(toggle(toggles, key, legend));
  };
  // Only a shown row isolates (A:3741).
  const isolate = (key: string, on: boolean) => {
    if (on) onDim(key);
  };
  // What is missing, said once. Rows found but none in them is an empty $500 snapshot (A:3569).
  const missing = () => {
    if (picked.ok || picked.missing === "grid") return text("costflow.c4.noGrid");
    if (picked.missing === "age")
      return text("costflow.c4.noAge", { day: dayLabel(view.now_day) ?? text("missing") });
    return text("costflow.noWindow", { window: shared.window });
  };

  return (
    <section
      className="wh-seller-panel"
      data-chart="costflow-4"
      aria-labelledby="wh-costflow-4"
    >
      <div className="wh-seller-head">
        <h3 id="wh-costflow-4">{title}</h3>
      </div>
      <div className="wh-ss-controls">
        <Segments
          label={text("costflow.window")}
          options={WINDOWS}
          value={shared.window}
          name={(w) => w}
          onPick={(w) => onShared({ window: w })}
        />
        {/* H:973: All, ±50% and ±25%; Chart 3's ±10% presses none of them. */}
        <Segments
          label={text("costflow.zoom")}
          options={ZOOMS4}
          value={shared.zoom}
          name={(z) => (z === 0 ? text("costflow.all") : `±${z}%`)}
          onPick={(z) => onShared({ zoom: z })}
        />
      </div>
      {picked.ok && plot && drawn ? (
        <>
          <WindowSpan view={view} w={shared.window} then={picked.value.then} />
          <FlowPlot
            prices={plot.prices}
            step={AGE_STEP}
            yDomain={plot.yDomain}
            mag={plot.mag}
            bars={plot.bars}
            curves={drawn.curves}
            marks={drawn.marks}
            spot={picked.value.spot}
            captions={[text("costflow.c4.axis.sell"), text("costflow.c4.axis.buy")]}
            label={title}
            dim={dim}
            active={reading}
            onActive={read}
          />
          <div className="wh-seller-legend wh-cf-legend">
            {legend.map((row) =>
              row.kind === "net" ? (
                <span key={row.key} className="wh-seller-key">
                  <i className="wh-seller-swatch wh-cf-swatch--net" aria-hidden="true" />
                  <span>{row.label}</span> <b>{row.value}</b>
                </span>
              ) : (
                <button
                  key={row.key}
                  type="button"
                  className="wh-ss-leg wh-seller-key"
                  aria-pressed={row.on}
                  onClick={() => flip(row.key)}
                  onMouseEnter={() => isolate(row.key, row.on)}
                  onMouseLeave={() => onDim(null)}
                  onFocus={() => isolate(row.key, row.on)}
                  onBlur={() => onDim(null)}
                >
                  <i
                    className={`wh-seller-swatch wh-cf-swatch--${row.kind} wh-cf-age-${row.band}`}
                    aria-hidden="true"
                  />
                  <span>{row.label}</span> <b>{row.value}</b>
                </button>
              ),
            )}
          </div>
          <div className="wh-cf-aging">
            <span className="wh-cf-note">{text("costflow.c4.note")}</span>
          </div>
          <div className="wh-cf-sides">
            {(["neg", "pos"] as const).map((which) => (
              <SideControls
                key={which}
                side={which}
                setting={sides[which]}
                curves={which === "pos" ? pos : neg}
                onSetting={(next) => setSides((current) => ({ ...current, [which]: next }))}
              />
            ))}
          </div>
          <div className="wh-cf-readout" aria-live="polite">
            {reading !== null
              ? ageTip(text, rows[reading], AGE_STEP, shared.window).map((line, i) => (
                  <p key={i}>{line}</p>
                ))
              : null}
          </div>
          <div className="wh-cf-tables">
            <ClustersTable
              rows={cs}
              spot={picked.value.spot}
              empty={text("costflow.c4.noClusters")}
            />
          </div>
        </>
      ) : (
        <p className="wh-onchain-warn">{missing()}</p>
      )}
      <ReadColumns shows="costflow.c4.shows" implies="costflow.c4.implies" how="costflow.c4.how" />
    </section>
  );
}

// The toggles Chart 4 keeps for new rows (another zoom, or a refresh): the same ones, unless the
// legend of those rows, drawn with them, would show no bought or sold row; then every row is on
// again (afterZoom), so a legend of only "off" rows never appears (N1, rule 3).
function keptToggles(text: TextFn, view: CostFlowView, w: Window, z: Zoom, t: Toggles): Toggles {
  const found = ageRows(view, w, z);
  return found.ok ? afterZoom(t, ageLegend(text, found.value, YOUNG[w], t, z)) : t;
}

function Charts({ view }: { view: CostFlowView }) {
  const { text } = useWheelhouseText();
  const [shared, setShared] = useState<Shared>(SHARED);
  // The bucket each chart reads; a new window or zoom replaces the rows, so both clear.
  const [active3, setActive3] = useState<Reading | null>(null);
  const [active4, setActive4] = useState<Reading | null>(null);
  // Chart 4's legend: which groups are drawn, and the one isolated by hover or focus.
  const [toggles, setToggles] = useState<Toggles>(ALL_ON);
  const [dim, setDim] = useState<string | null>(null);
  // A refresh brings new rows: the toggles must still leave a row shown, and the isolated row may
  // be gone (its button unmounts without a mouseleave). Adjusted while rendering, so no frame is
  // drawn with the old state.
  const [seen, setSeen] = useState(view);
  if (seen !== view) {
    setSeen(view);
    setDim(null);
    setToggles(keptToggles(text, view, shared.window, shared.zoom, toggles));
  }
  // N1: a window button in either chart turns every group on again (A:3820-3823). A zoom keeps
  // the toggles unless the new zoom's legend, drawn with them, would show no row.
  const onShared = (next: Partial<Shared>) => {
    setActive3(null);
    setActive4(null);
    setDim(null);
    if (next.window !== undefined) setToggles(ALL_ON);
    if (next.zoom !== undefined)
      setToggles(keptToggles(text, view, shared.window, next.zoom, toggles));
    setShared((current) => ({ ...current, ...next }));
  };
  return (
    <>
      <Chart3
        view={view}
        shared={shared}
        onShared={onShared}
        active={active3}
        onActive={setActive3}
      />
      <Chart4
        view={view}
        shared={shared}
        onShared={onShared}
        toggles={toggles}
        onToggles={setToggles}
        dim={dim}
        onDim={setDim}
        active={active4}
        onActive={setActive4}
      />
    </>
  );
}

export function CostFlowCharts() {
  const { text } = useWheelhouseText();
  const query = useQuery({
    queryKey: ["wh", "onchain", "cost-flow"],
    queryFn: ({ signal }) => getCostFlow(signal),
    // The worker derives once an hour; polling more often only resends the same payload.
    refetchInterval: 300000,
    retry: false,
  });
  const data = query.data;

  // A failed request wins over older data: the charts must not look current when they are not.
  if (query.isError) {
    const failure = String(query.error.message ?? "");
    return (
      <div className="wh-seller wh-costflow">
        <p className="wh-onchain-warn">{text("costflow.unavailable")}</p>
        {failure ? <p className="wh-muted">{failure}</p> : null}
      </div>
    );
  }
  if (!data)
    return (
      <div className="wh-seller wh-costflow">
        <p className="wh-muted">{text("costflow.loading")}</p>
      </div>
    );

  const reasons = data.reasons.length ? (
    <p className="wh-muted">
      {data.reasons.map((reason) => reasonText(text, reason)).join(" · ")}
    </p>
  ) : null;
  const refreshing = data.refreshing ? (
    <p role="status">{text("levels.refreshing")}</p>
  ) : null;
  if (data.data_state === "unavailable")
    return (
      <div className="wh-seller wh-costflow">
        <p className="wh-onchain-warn">{text("costflow.unavailable")}</p>
        {reasons}
        {refreshing}
      </div>
    );

  const missing = text("missing");
  return (
    <div className="wh-seller wh-costflow">
      <p className="wh-seller-meta">
        {/* The snapshot's day, D: fetched after D ended, it is D's close, not the fetch's day. */}
        {data.forming_at
          ? text("costflow.meta", {
              day: dayLabel(data.now_day) ?? missing,
              time: timeLabel(data.snapshot_at) ?? missing,
            })
          : text("costflow.metaClosed", { day: dayLabel(data.now_day) ?? missing })}
      </p>
      {data.forming_at ? (
        <p className="wh-seller-meta">
          {text("costflow.forming", { day: dayLabel(data.forming_at) ?? missing })}
        </p>
      ) : null}
      {data.data_state === "stale" ? (
        <p className="wh-onchain-warn">
          {text("costflow.stale", { day: dayLabel(data.now_day) ?? missing })}
        </p>
      ) : null}
      {data.qc.length ? (
        <p className="wh-onchain-warn">
          {text("costflow.qc", { list: data.qc.map((code) => qcText(text, code)).join(", ") })}
        </p>
      ) : null}
      {refreshing}
      {reasons}
      {rulesNote(text, data).map((line) => (
        <p key={line} className="wh-seller-meta">
          {line}
        </p>
      ))}
      <Charts view={data} />
    </div>
  );
}

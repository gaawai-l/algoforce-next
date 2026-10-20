import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { getCostBasisHistory } from "./client";
import {
  CBH_SPANS,
  DEFAULT_CONTRAST,
  DEFAULT_SPAN,
  RAMP,
  RANGES,
  STEP,
  UNDER_FLOOR,
  clampHandle,
  contrast,
  contrastLabel,
  coverage,
  dayLabel,
  dayTicks,
  fmtDays,
  fmtK,
  keyLabels,
  occupiedRows,
  paint,
  sortedCells,
  tipParts,
  visibleWindow,
  zoomFromDrag,
  zoomText,
  type Contrast,
  type RangePct,
  type SpanKey,
  type Visible,
} from "./cost-basis-history";
import { ReadColumns } from "./flow-notes";
import { useWheelhouseText, type TextFn } from "./i18n";
import type { CostBasisHistoryView } from "./onchain-contract";
import { reasonText, rulesNote } from "./onchain-text";
import { useChartWidth } from "./seller-charts";
import { heightFor, ticks } from "./sell-side";
import { Segments } from "./sell-side-charts";

// Chart 8, Cost Basis Distribution, All Coins, as on the original state-report page (A =
// raw/script_2_app.js, A:532-565 and A:3914-4330): the supply in each $500 cost-basis bucket, one
// column per day, under the spot line. The cells are one canvas pixel each, painted by `paint`; the
// axes, the missing and forming days, the spot line, the cursor and the drag box are an SVG laid
// over the canvas. Every number shown is a string from cost-basis-history.ts.

const DAY = 864e5;
const round = (value: number) => Math.round(value * 100) / 100;
const clamp = (value: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, value));
const daysOf = (span: SpanKey) => CBH_SPANS.find((item) => item.key === span)!.days;
// The worker writes the history once an hour; All, the longest body, is asked for no more often.
const refetchFor = (span: SpanKey) => (span === "all" ? 3_600_000 : 900_000);

type Zoom = { zx: [string, string] | null; zy: [number, number] | null };
interface Cell {
  i: number;
  r: number;
}
// A reading belongs to the payload it was taken on.
interface Reading extends Cell {
  view: CostBasisHistoryView;
}
interface Point {
  x: number;
  y: number;
}
interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

// The plot inside the svg: column i is the band [i, i + 1) * plotW / n (plan R13a), row r1 is at
// the top, and the price axis runs from the lowest row's floor to the top of the highest (A:4088).
function frame(width: number, height: number, n: number, floors: number[], r0: number, r1: number) {
  const left = width < 500 ? 44 : 56;
  const top = 10;
  const plotW = Math.max(40, width - left - 12);
  const plotH = height - top - 24;
  const yLo = floors[r0];
  const yHi = floors[r1] + STEP;
  return {
    left,
    top,
    plotW,
    plotH,
    yLo,
    yHi,
    col: plotW / n,
    x: (i: number) => left + ((i + 0.5) * plotW) / n,
    y: (price: number) => top + (plotH * (yHi - price)) / (yHi - yLo),
  };
}

// The runs of days without a snapshot, pending or absent alike: each is one hatched rect.
function missingRuns(vis: Visible) {
  const runs: { start: number; days: number }[] = [];
  vis.supply.forEach((row, i) => {
    if (row) return;
    const last = runs[runs.length - 1];
    if (last && last.start + last.days === i) last.days += 1;
    else runs.push({ start: i, days: 1 });
  });
  return runs;
}

// The spot line through each column's centre, broken where a day has no close and held to the
// plot where the close is off the price axis (A:4100).
function spotPath(vis: Visible, f: ReturnType<typeof frame>) {
  let d = "";
  let pen = false;
  vis.close.forEach((close, i) => {
    if (close === null) {
      pen = false;
      return;
    }
    const y = clamp(f.y(close), f.top, f.top + f.plotH);
    d += `${pen ? "L" : "M"}${round(f.x(i))},${round(y)}`;
    pen = true;
  });
  return d;
}

function CbhPlot({
  vis,
  floors,
  r0,
  r1,
  c,
  reading,
  onRead,
  onZoom,
  onReset,
  label,
  text,
}: {
  vis: Visible;
  floors: number[];
  r0: number;
  r1: number;
  c: Contrast;
  reading: Cell | null;
  onRead: (cell: Cell | null) => void;
  onZoom: (next: Zoom) => void;
  onReset: () => void;
  label: string;
  text: TextFn;
}) {
  // Mounted only with rows to draw, so the width observer starts on the drawn svg.
  const [ref, width] = useChartWidth();
  const height = heightFor(width);
  const canvas = useRef<HTMLCanvasElement>(null);
  const uid = useId().replace(/[^\w-]/g, "");
  const [drag, setDrag] = useState<Box | null>(null);
  const n = vis.days.length;
  const rows = r1 - r0 + 1;
  const f = frame(width, height, n, floors, r0, r1);
  const runs = useMemo(() => missingRuns(vis), [vis]);

  useEffect(() => {
    const context = canvas.current?.getContext("2d");
    if (!context) return;
    const image = context.createImageData(n, rows);
    paint(vis, r0, r1, c, image.data);
    context.putImageData(image, 0, 0);
  }, [vis, r0, r1, c, n, rows]);

  const first = vis.days[0];
  const last = vis.days[n - 1];
  const spanDays = (Date.parse(last) - Date.parse(first)) / DAY;
  const forming = vis.status.indexOf("forming");
  const formingW = Math.max(f.col, 3);

  const local = (event: PointerEvent<SVGSVGElement>): Point | null => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) return null;
    return {
      x: ((event.clientX - box.left) / box.width) * width,
      y: ((event.clientY - box.top) / box.height) * height,
    };
  };
  const inside = (p: Point) =>
    p.x >= f.left && p.x <= f.left + f.plotW && p.y >= f.top && p.y <= f.top + f.plotH;
  // The cell under a point: its column band, and the $500 row of its price (A:4274).
  const cellAt = (p: Point): Cell | null => {
    if (!inside(p)) return null;
    const price = f.yHi - ((p.y - f.top) / f.plotH) * (f.yHi - f.yLo);
    return {
      i: clamp(Math.floor((p.x - f.left) / f.col), 0, n - 1),
      r: clamp(Math.floor((price - floors[0]) / STEP), r0, r1),
    };
  };
  const toPlot = (p: Point): Point => ({
    x: clamp(p.x - f.left, 0, f.plotW),
    y: clamp(p.y - f.top, 0, f.plotH),
  });
  const down = (event: PointerEvent<SVGSVGElement>) => {
    const p = local(event);
    if (!p) return;
    // Only a mouse drags a box; a touch reads the cell and leaves the page free to scroll.
    if (event.pointerType === "mouse" && event.button === 0 && inside(p)) {
      // jsdom has no pointer capture.
      event.currentTarget.setPointerCapture?.(event.pointerId);
      const q = toPlot(p);
      setDrag({ x0: q.x, y0: q.y, x1: q.x, y1: q.y });
    }
    onRead(cellAt(p));
  };
  const move = (event: PointerEvent<SVGSVGElement>) => {
    const p = local(event);
    if (!p) return;
    if (drag) {
      const q = toPlot(p);
      setDrag({ ...drag, x1: q.x, y1: q.y });
    }
    onRead(cellAt(p));
  };
  const up = (event: PointerEvent<SVGSVGElement>) => {
    if (!drag) return;
    const p = local(event);
    const q = p ? toPlot(p) : { x: drag.x1, y: drag.y1 };
    setDrag(null);
    const next = zoomFromDrag(
      { x0: drag.x0, x1: q.x, y0: drag.y0, y1: q.y },
      { width: f.plotW, height: f.plotH },
      vis.days,
      f.yLo,
      f.yHi,
    );
    if (next) onZoom(next);
  };
  // Keyboard reading starts on the newest day, at the row of the latest close.
  const start = (): Cell => {
    let i = n - 1;
    while (i > 0 && vis.close[i] === null) i -= 1;
    const close = vis.close[i];
    return {
      i: n - 1,
      r: close === null ? r1 : clamp(Math.floor((close - floors[0]) / STEP), r0, r1),
    };
  };
  const key = (event: KeyboardEvent<SVGSVGElement>) => {
    const at = reading ?? start();
    const next: Record<string, Cell | null> = {
      ArrowLeft: { i: Math.max(0, at.i - 1), r: at.r },
      ArrowRight: { i: Math.min(n - 1, at.i + 1), r: at.r },
      ArrowUp: { i: at.i, r: Math.min(r1, at.r + 1) },
      ArrowDown: { i: at.i, r: Math.max(r0, at.r - 1) },
      Home: { i: 0, r: at.r },
      End: { i: n - 1, r: at.r },
      Escape: null,
    };
    if (!(event.key in next)) return;
    // The arrows and Home/End would scroll the page as well.
    event.preventDefault();
    onRead(next[event.key]);
  };

  const tip = reading ? tipParts(vis, reading.i, reading.r, floors) : null;
  const tipForming = reading !== null && vis.status[reading.i] === "forming";
  const cx = reading ? f.x(reading.i) : 0;
  // The reading sits beside the cursor, on whichever side has room.
  const place: CSSProperties =
    cx < width * 0.6 ? { left: round(cx + 14) } : { right: round(width - cx + 14) };
  const spot = spotPath(vis, f);

  return (
    <div className="wh-cbh-plot">
      <canvas
        ref={canvas}
        className="wh-cbh-canvas"
        width={n}
        height={rows}
        data-cols={n}
        data-rows={rows}
        style={{ left: f.left, top: f.top, width: round(f.plotW), height: round(f.plotH) }}
        aria-hidden="true"
      />
      <svg
        ref={ref}
        className="wh-cbh-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={label}
        tabIndex={0}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={() => setDrag(null)}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse" && !drag) onRead(null);
        }}
        onDoubleClick={onReset}
        onKeyDown={key}
        onBlur={() => onRead(null)}
      >
        <defs>
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
        {ticks(f.yLo, f.yHi, 7).map((v) => (
          <text
            key={v}
            className="wh-seller-tick"
            x={f.left - 6}
            y={round(f.y(v) + 3.5)}
            textAnchor="end"
          >
            {fmtK(v)}
          </text>
        ))}
        {dayTicks(first, last, Math.max(2, Math.min(8, Math.floor(f.plotW / 110)))).map((day) => (
          <text
            key={day}
            className="wh-seller-tick"
            x={round(f.x(vis.days.indexOf(day)))}
            y={f.top + f.plotH + 16}
            textAnchor="middle"
          >
            {dayLabel(day, spanDays)}
          </text>
        ))}
        <text className="wh-seller-tick" x="2" y={f.top + f.plotH + 16}>
          UTC
        </text>
        {runs.map((run) => (
          <rect
            key={run.start}
            className="wh-cbh-missing"
            data-missing="true"
            data-days={run.days}
            x={round(f.left + run.start * f.col)}
            y={f.top}
            width={round(run.days * f.col)}
            height={round(f.plotH)}
            fill={`url(#${uid}-hatch)`}
          />
        ))}
        {forming >= 0 ? (
          <rect
            className="wh-seller-forming"
            data-forming="true"
            x={round(f.x(forming) - formingW / 2)}
            y={f.top}
            width={round(formingW)}
            height={round(f.plotH)}
          />
        ) : null}
        <path className="wh-cbh-price-case" d={spot} />
        <path className="wh-cbh-price" d={spot} />
        {reading ? (
          <>
            <line
              className="wh-seller-cursor"
              x1={round(cx)}
              x2={round(cx)}
              y1={f.top}
              y2={f.top + f.plotH}
            />
            <line
              className="wh-seller-cursor"
              x1={f.left}
              x2={round(f.left + f.plotW)}
              y1={round(f.y(floors[reading.r] + STEP / 2))}
              y2={round(f.y(floors[reading.r] + STEP / 2))}
            />
          </>
        ) : null}
        {drag ? (
          <rect
            className="wh-cbh-drag"
            x={round(f.left + Math.min(drag.x0, drag.x1))}
            y={round(f.top + Math.min(drag.y0, drag.y1))}
            width={round(Math.abs(drag.x1 - drag.x0))}
            height={round(Math.abs(drag.y1 - drag.y0))}
          />
        ) : null}
      </svg>
      {tip ? (
        <div className="wh-cbh-tip" aria-live="polite" style={place}>
          <div className="wh-cbh-tip-day">{tip.day}</div>
          {"missing" in tip ? (
            <div>{text(tip.missing === "absent" ? "cbh.absentDay" : "cbh.pendingDay")}</div>
          ) : (
            <>
              <div>{`${text("cbh.bucket")} ${tip.bucket}`}</div>
              <div>{`${text("cbh.supply")} ${tip.supply}`}</div>
              {tip.spot !== null ? <div>{`${text("cbh.spot")} ${tip.spot}`}</div> : null}
              {tipForming ? <div className="wh-cbh-tip-forming">{text("cbh.forming")}</div> : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

export function CostBasisHistoryChart() {
  const { text } = useWheelhouseText();
  const titleId = useId();
  const [span, setSpan] = useState<SpanKey>(DEFAULT_SPAN);
  const [range, setRange] = useState<RangePct>(0);
  const [lo, setLo] = useState<number>(DEFAULT_CONTRAST.lo);
  const [hi, setHi] = useState<number>(DEFAULT_CONTRAST.hi);
  const [zx, setZx] = useState<[string, string] | null>(null);
  const [zy, setZy] = useState<[number, number] | null>(null);
  const [reading, setReading] = useState<Reading | null>(null);
  const query = useQuery({
    queryKey: ["wh", "onchain", "cost-basis-history", span],
    queryFn: ({ signal }) => getCostBasisHistory(span, signal),
    refetchInterval: refetchFor(span),
    retry: false,
    // A new span keeps the chart on screen until its days arrive.
    placeholderData: (previous) => previous,
  });
  // The last span that loaded, drawn on when a newly picked span fails to load (plan R18).
  const [good, setGood] = useState<{ span: SpanKey; view: CostBasisHistoryView } | null>(null);
  const fresh = query.isPlaceholderData ? undefined : query.data;
  if (fresh && (good === null || good.view !== fresh || good.span !== span))
    setGood({ span, view: fresh });
  const failedNew = query.isError && good !== null && good.span !== span;
  // The span on screen failing to refresh wins over its older days, as on Sell side.
  const view = query.isError ? (failedNew ? good.view : undefined) : query.data;

  const win = useMemo(() => (view ? visibleWindow(view, zx) : null), [view, zx]);
  // A dragged window of under two days is dropped.
  if (win && win.zx !== zx) setZx(win.zx);
  const rows = useMemo(
    () => (view && win ? occupiedRows(view.floors, win.vis, range, zy) : null),
    [view, win, range, zy],
  );
  // So is a dragged band that keeps no row.
  if (rows && rows.zy !== zy) setZy(rows.zy);
  const vis = win?.vis ?? null;
  const r0 = rows?.r0 ?? null;
  const r1 = rows?.r1 ?? null;
  // Sorted once per window and rows: moving a Contrast handle only reads other quantiles.
  const sorted = useMemo(
    () => (vis && r0 !== null && r1 !== null ? sortedCells(vis, r0, r1) : null),
    [vis, r0, r1],
  );
  // Rows where no cell holds coins have nothing to scale: they are no data, never a 0-1 key.
  const c = useMemo(
    () => (sorted && sorted.length ? contrast(sorted, lo, hi) : null),
    [sorted, lo, hi],
  );
  const read = reading !== null && reading.view === view ? reading : null;

  // Every input that changes what is drawn clears the reading.
  const pickSpan = (next: SpanKey) => {
    setReading(null);
    if (next === span) {
      // Picking the span that failed to load asks for it again (plan R18).
      if (query.isError) void query.refetch();
      return;
    }
    setSpan(next);
    setZx(null);
  };
  const pickRange = (next: RangePct) => {
    setReading(null);
    setRange(next);
    setZy(null);
  };
  const slide = (which: "lo" | "hi") => (event: ChangeEvent<HTMLInputElement>) => {
    setReading(null);
    const [nextLo, nextHi] = clampHandle(which, Number(event.target.value), lo, hi);
    setLo(nextLo);
    setHi(nextHi);
  };
  // zoomFromDrag leaves an axis the box did not change at null: that axis keeps its zoom.
  const zoom = (next: Zoom) => {
    setReading(null);
    setZx((current) => next.zx ?? current);
    setZy((current) => next.zy ?? current);
  };
  const reset = () => {
    setReading(null);
    setZx(null);
    setZy(null);
  };

  const spanControl = (
    <Segments
      label={text("cbh.span")}
      options={CBH_SPANS.map((item) => item.key)}
      value={span}
      name={(key) => (key === "all" ? text("cbh.all") : text("cbh.days", { n: daysOf(key) }))}
      title={(key) => (key === "all" ? text("cbh.allTitle") : undefined)}
      onPick={pickSpan}
    />
  );
  const section = (body: ReactNode) => (
    <section
      className="wh-seller wh-seller-panel wh-cbh"
      data-chart="cost-basis-history"
      aria-labelledby={titleId}
    >
      <div className="wh-seller-head">
        <h3 id={titleId}>{text("cbh.title")}</h3>
      </div>
      {body}
    </section>
  );

  if (query.isError && !failedNew) {
    const failure = String(query.error.message ?? "");
    // Span stays, so another span, or this one again, can be asked for.
    return section(
      <>
        <p className="wh-onchain-warn">{text("cbh.unavailable")}</p>
        {failure ? <p className="wh-muted">{failure}</p> : null}
        <div className="wh-ss-controls">{spanControl}</div>
      </>,
    );
  }
  if (!view || !win) return section(<p className="wh-muted">{text("cbh.loading")}</p>);

  const reasons = view.reasons.length ? (
    <p className="wh-muted">{view.reasons.map((reason) => reasonText(text, reason)).join(" · ")}</p>
  ) : null;
  const refreshing = view.refreshing ? <p role="status">{text("levels.refreshing")}</p> : null;
  if (view.data_state === "unavailable")
    return section(
      <>
        <p className="wh-onchain-warn">{text("cbh.unavailable")}</p>
        {reasons}
        {refreshing}
      </>,
    );

  const missing = text("missing");
  const cov = coverage(win.vis);
  const status = [
    text("cbh.meta", { day: view.latest_day ?? missing }),
    text("cbh.coverage", { have: fmtDays(cov.have), want: fmtDays(cov.want) }),
  ];
  // A failed round keeps the backfill gate shut, whatever the last backfill did (plan R21).
  if (cov.pending)
    status.push(
      view.last_error !== null
        ? text("cbh.held", { code: view.last_error })
        : view.backfill_error !== null
          ? text("cbh.paused", { code: view.backfill_error })
          : text("cbh.backfilling"),
    );
  if (cov.absent)
    status.push(
      cov.absent === 1 ? text("cbh.absentOne") : text("cbh.absentMany", { n: fmtDays(cov.absent) }),
    );
  if (cov.forming) status.push(text("cbh.formingNote"));
  const zoomed = zx !== null || zy !== null;
  const days = fmtDays(daysOf(span));
  const labels = c ? keyLabels(c) : null;

  return section(
    <>
      <p className="wh-seller-meta">{status.join(" · ")}</p>
      {rulesNote(text, view).map((line) => (
        <p key={line} className="wh-seller-meta">
          {line}
        </p>
      ))}
      {view.data_state === "stale" ? (
        <p className="wh-onchain-warn">{text("cbh.stale", { day: view.latest_day ?? missing })}</p>
      ) : null}
      {refreshing}
      {reasons}
      <div className="wh-ss-controls">
        {spanControl}
        <Segments
          label={text("cbh.range")}
          options={RANGES}
          value={range}
          name={(pct) => (pct === 0 ? text("cbh.all") : `±${pct}%`)}
          onPick={pickRange}
        />
        <div className="wh-ss-control wh-cbh-contrast">
          <span className="wh-ss-label">{text("cbh.contrast")}</span>
          <span className="wh-cbh-track">
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={lo}
              aria-label={text("cbh.lower")}
              onChange={slide("lo")}
            />
            <input
              type="range"
              min={0}
              max={100}
              step={1}
              value={hi}
              aria-label={text("cbh.upper")}
              onChange={slide("hi")}
            />
          </span>
          {c ? (
            <span className="wh-cbh-level">
              {contrastLabel(c, lo, hi) ?? text("cbh.fullRange")}
            </span>
          ) : null}
        </div>
        <div className="wh-ss-control">
          <span className="wh-cbh-zoom">
            {zoomed ? `${zoomText(zx, zy)} · ${text("cbh.zoomReset")}` : text("cbh.zoomHint")}
          </span>
          {zoomed ? (
            <button type="button" className="wh-cbh-reset" onClick={reset}>
              {text("cbh.reset")}
            </button>
          ) : null}
        </div>
        {query.isPlaceholderData ? (
          <span className="wh-cbh-load" role="status">
            {text("cbh.fetching", { n: days })}
          </span>
        ) : failedNew ? (
          <span className="wh-cbh-load wh-cbh-load--failed" role="status">
            {text("cbh.couldNotLoad", { n: days })}
          </span>
        ) : null}
      </div>
      {rows && c ? (
        <CbhPlot
          vis={win.vis}
          floors={view.floors}
          r0={rows.r0}
          r1={rows.r1}
          c={c}
          reading={read}
          onRead={(cell) => setReading(cell ? { ...cell, view } : null)}
          onZoom={zoom}
          onReset={reset}
          label={text("cbh.aria")}
          text={text}
        />
      ) : (
        // Missing is said, never drawn as zero.
        <p className="wh-muted">{text(cov.have === 0 ? "cbh.noneStored" : "seller.noData")}</p>
      )}
      {c && labels ? (
        <div className="wh-cbh-key">
          <span className="wh-ss-label">{text("cbh.supplyBtc")}</span>
          {c.dropped ? (
            <span className="wh-cbh-step">
              <i className="wh-cbh-swatch" style={{ background: UNDER_FLOOR }} aria-hidden="true" />
              {text("cbh.belowFloor")}
            </span>
          ) : null}
          {RAMP.map((colour, k) => (
            <span key={colour} className="wh-cbh-step">
              <i className="wh-cbh-swatch" style={{ background: colour }} aria-hidden="true" />
              <b className="wh-cbh-mark">{labels[k]}</b>
            </span>
          ))}
          <b className="wh-cbh-mark">{labels[4]}</b>
        </div>
      ) : null}
      <p className="wh-ss-foot">{text("cbh.caption")}</p>
      <ReadColumns shows="cbh.shows" implies="cbh.implies" how="cbh.how" />
    </>,
  );
}

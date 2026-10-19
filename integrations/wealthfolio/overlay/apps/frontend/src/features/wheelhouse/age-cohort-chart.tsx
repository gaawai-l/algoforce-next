import {
  useMemo,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";
import {
  DEFAULT_AGE_CHOICE,
  DETAILS,
  SCALES,
  ageAxis,
  ageTip,
  bandsFor,
  buildAgeRows,
  fmtAge,
  fmtShare,
  isShown,
  legendValue,
  priceAxis,
  toggleBand,
  withDetail,
  withSolo,
  type AgeChoice,
  type AgeRow,
  type Axis,
} from "./age-cohorts";
import { getAgeCohorts } from "./client";
import { useWheelhouseText, type TextFn } from "./i18n";
import type { AgeCohortsView } from "./onchain-contract";
import { reasonText, rulesNote } from "./onchain-text";
import { timeTicks, useChartWidth } from "./seller-charts";
import { MEASURES, SMOOTHINGS, SPANS, si } from "./sell-side";
import { Segments } from "./sell-side-charts";

const HOUR = 3_600_000;
const round = (value: number) => Math.round(value * 100) / 100;
const utcStamp = (t: number) =>
  new Date(t).toISOString().slice(0, 16).replace("T", " ");
// Each band takes its colour from the original's age ramp, light for young and dark for old.
const tone = (detail: number, band: number) => `var(--wh-age${detail}-${band})`;

// The plot's height follows its width, like the original's 940x440, between 300 and 440 px.
const heightFor = (width: number) =>
  Math.round(Math.min(440, Math.max(300, width * 0.47)));

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

const tickLabel = (v: number, choice: AgeChoice) =>
  choice.scale === "pct" ? fmtShare(Math.abs(v)) : fmtAge(Math.abs(v), choice.measure);

// Room for the widest value label, "200k BTC" and the like, at 10px JetBrains Mono.
const leftFor = (width: number, axis: Axis, choice: AgeChoice) =>
  Math.max(
    width < 500 ? 40 : 64,
    Math.ceil(Math.max(...axis.ticks.map((v) => tickLabel(v, choice).length)) * 6.1) + 12,
  );

function frame(width: number, height: number, rows: AgeRow[], left: number): Frame {
  const compact = width < 500;
  const right = compact ? 44 : 56;
  // Room above for "profit ↑", and below the time axis for "loss ↓".
  const top = 18;
  const bottom = 38;
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

function nearest(rows: AgeRow[], t: number) {
  let lo = 0;
  let hi = rows.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].t < t) lo = mid + 1;
    else hi = mid;
  }
  return lo > 0 && t - rows[lo - 1].t < rows[lo].t - t ? lo - 1 : lo;
}

const scale = (f: Frame, axis: Axis) => (v: number) =>
  f.top + (f.plotH * (axis.hi - v)) / (axis.hi - axis.lo);

// Profit stacks up from the zero line and loss down from it, youngest band nearest the line.
// Each band is one path, so tens of thousands of cells stay a dozen elements.
function geometry(
  rows: AgeRow[],
  choice: AgeChoice,
  width: number,
  height: number,
  axis: Axis,
  left: number,
) {
  const f = frame(width, height, rows, left);
  const y = scale(f, axis);
  const bands = bandsFor(choice.detail);
  const pct = choice.scale === "pct";
  const barW = round(Math.max(0.6, f.slot - (rows.length > 240 ? 0 : 1)));
  const paths = bands.map(() => "");
  const extent = rows.map(() => [0, 0]);
  let cells = 0;
  rows.forEach((row, r) => {
    const x = round(f.x(row.t) - barW / 2);
    let up = 0;
    let down = 0;
    bands.forEach((band, b) => {
      if (!isShown(band, choice.on)) return;
      const pv = pct ? row.p[b] / row.tot : row.p[b];
      const lv = pct ? row.l[b] / row.tot : row.l[b];
      if (pv > 0) {
        const top = round(y(up + pv));
        paths[b] += `M${x},${top}h${barW}V${round(y(up))}h${-barW}z`;
        up += pv;
        cells += 1;
      }
      if (lv > 0) {
        const top = round(y(-down));
        paths[b] += `M${x},${top}h${barW}V${round(y(-down - lv))}h${-barW}z`;
        down += lv;
        cells += 1;
      }
    });
    extent[r] = [up, down];
  });
  return { paths, extent, barW, cells };
}

interface LayerProps {
  rows: AgeRow[];
  choice: AgeChoice;
  axis: Axis;
  left: number;
  formingT: number | null;
  isolate: number | null;
  width: number;
  height: number;
  text: TextFn;
}

function Layer({
  rows,
  choice,
  axis,
  left,
  formingT,
  isolate,
  width,
  height,
  text,
}: LayerProps) {
  const f = frame(width, height, rows, left);
  const y = scale(f, axis);
  // Hovering the legend only changes the bands' opacity, never their shapes.
  const drawn = useMemo(
    () => geometry(rows, choice, width, height, axis, left),
    [rows, choice, width, height, axis, left],
  );
  const price = priceAxis(rows);
  const py = (v: number) =>
    f.top + (f.plotH * (price.hi - v)) / (price.hi - price.lo);
  const pricePath = rows
    .map((row, i) => `${i ? "L" : "M"}${round(f.x(row.t))},${round(py(row.px))}`)
    .join("");
  const forming =
    formingT == null ? -1 : rows.findIndex((row) => row.t === formingT);

  return (
    <>
      {axis.ticks.map((v) => (
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
            {tickLabel(v, choice)}
          </text>
        </g>
      ))}
      {timeTicks(f.t0, f.t1, Math.max(2, Math.floor(f.plotW / 64))).map(
        ([t, label]) => (
          <text
            key={t}
            className="wh-seller-tick"
            x={round(f.x(t))}
            y={f.top + f.plotH + 14}
            textAnchor="middle"
          >
            {label}
          </text>
        ),
      )}
      <text className="wh-seller-tick" x="2" y={f.top + f.plotH + 14}>
        UTC
      </text>
      <text className="wh-seller-tick wh-age-cap" x="2" y="11">
        {text("agecohorts.profit")}
      </text>
      <text className="wh-seller-tick wh-age-cap" x="2" y={height - 4}>
        {text("agecohorts.loss")}
      </text>
      <g data-cells={drawn.cells}>
        {drawn.paths.map((d, b) =>
          d ? (
            <path
              key={`${choice.detail}-${b}`}
              className="wh-age-band"
              data-band={b}
              d={d}
              style={{ fill: tone(choice.detail, b) }}
              fillOpacity={isolate !== null && isolate !== b ? 0.15 : 1}
            />
          ) : null,
        )}
      </g>
      <line
        className="wh-age-zero"
        x1={f.left}
        x2={f.left + f.plotW}
        y1={round(y(0))}
        y2={round(y(0))}
      />
      <path className="wh-seller-price" d={pricePath} />
      {price.ticks.map((v) => (
        <text
          key={v}
          className="wh-seller-tick wh-seller-tick--price"
          x={f.left + f.plotW + 6}
          y={round(py(v) + 3.5)}
        >
          {`$${si(v)}`}
        </text>
      ))}
      {forming >= 0 ? (
        <rect
          className="wh-seller-forming"
          data-forming="true"
          x={round(f.x(formingT as number) - Math.max(drawn.barW + 2, 5) / 2)}
          y={round(y(drawn.extent[forming][0]))}
          width={round(Math.max(drawn.barW + 2, 5))}
          height={round(
            y(-drawn.extent[forming][1]) - y(drawn.extent[forming][0]),
          )}
        />
      ) : null}
    </>
  );
}

function Plot({
  rows,
  choice,
  formingT,
  isolate,
  label,
  hover,
  onHover,
  text,
}: Omit<LayerProps, "width" | "height" | "axis" | "left"> & {
  label: string;
  hover: number | null;
  onHover: (index: number | null) => void;
}) {
  const [ref, width] = useChartWidth();
  const height = heightFor(width);
  const axis = useMemo(() => ageAxis(rows, choice), [rows, choice]);
  const left = leftFor(width, axis, choice);
  const f = frame(width, height, rows, left);
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
      End: last,
      Escape: null,
    };
    if (!(event.key in next)) return;
    event.preventDefault();
    onHover(next[event.key]);
  };
  const row = hover != null ? rows[hover] : undefined;
  const tip = row ? ageTip(row, choice) : null;
  const x = row ? f.x(row.t) : 0;
  // The reading sits beside the cursor, on whichever side has room.
  const place: CSSProperties =
    x < width * 0.6 ? { left: round(x + 14) } : { right: round(width - x + 14) };
  return (
    <div className="wh-age-wrap">
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
          rows={rows}
          choice={choice}
          axis={axis}
          left={left}
          formingT={formingT}
          isolate={isolate}
          width={width}
          height={height}
          text={text}
        />
        {row ? (
          <line
            className="wh-seller-cursor"
            x1={round(x)}
            x2={round(x)}
            y1={f.top}
            y2={f.top + f.plotH}
          />
        ) : null}
      </svg>
      {tip ? (
        <div className="wh-age-tip" role="status" style={place}>
          <div className="wh-age-tip-title">{tip.title}</div>
          {tip.lines.map((line) => (
            <div key={line.band} className="wh-age-tip-row">
              <span>
                <i
                  className="wh-seller-swatch"
                  style={{ background: tone(choice.detail, line.band) }}
                  aria-hidden="true"
                />
                {line.name}
              </span>
              <span>{line.text}</span>
            </div>
          ))}
          <div className="wh-age-tip-foot">
            {text("agecohorts.tipFoot", { total: tip.total, spot: tip.spot })}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Controls({
  choice,
  onChoice,
  text,
}: {
  choice: AgeChoice;
  // Each change applies to the choice current when it lands, so quick clicks never undo each other.
  onChoice: (update: (current: AgeChoice) => AgeChoice) => void;
  text: TextFn;
}) {
  return (
    <div className="wh-ss-controls">
      <Segments
        label={text("sellside.span")}
        options={SPANS.map((span) => span.rows)}
        value={choice.span}
        name={(rows) => SPANS.find((span) => span.rows === rows)?.label ?? ""}
        onPick={(span) => onChoice((current) => ({ ...current, span }))}
      />
      <Segments
        label={text("sellside.smoothing")}
        options={SMOOTHINGS}
        value={choice.smoothing as (typeof SMOOTHINGS)[number]}
        name={(hours) => `${hours}h`}
        onPick={(smoothing) => onChoice((current) => ({ ...current, smoothing }))}
      />
      <Segments
        label={text("sellside.measure")}
        options={MEASURES}
        value={choice.measure}
        name={(measure) => text(`sellside.measure.${measure}`)}
        onPick={(measure) => onChoice((current) => ({ ...current, measure }))}
      />
      <Segments
        label={text("agecohorts.detail")}
        options={DETAILS}
        value={choice.detail}
        name={(detail) => text(`agecohorts.detail.${detail}`)}
        onPick={(detail) => onChoice((current) => withDetail(current, detail))}
      />
      <Segments
        label={text("agecohorts.scale")}
        options={SCALES}
        value={choice.scale}
        name={(scale) => text(`agecohorts.scale.${scale}`)}
        onPick={(scale) => onChoice((current) => ({ ...current, scale }))}
      />
      <div className="wh-ss-control">
        <span className="wh-ss-label">{text("agecohorts.cohorts")}</span>
        <label className="wh-inline wh-age-solo">
          <input
            type="checkbox"
            checked={choice.solo}
            onChange={(event) => {
              const solo = event.target.checked;
              onChoice((current) => withSolo(current, solo));
            }}
          />
          {text("agecohorts.solo")}
        </label>
      </div>
    </div>
  );
}

function Panel({ view }: { view: AgeCohortsView }) {
  const { text } = useWheelhouseText();
  const [choice, setChoice] = useState<AgeChoice>(DEFAULT_AGE_CHOICE);
  const [hover, setHover] = useState<number | null>(null);
  const [isolate, setIsolate] = useState<number | null>(null);
  const rows = useMemo(() => buildAgeRows(view, choice), [view, choice]);
  const title = text("agecohorts.title");
  const formingT = view.forming_at ? Date.parse(view.forming_at) : null;
  const bands = bandsFor(choice.detail);
  const shown = bands.filter((band) => isShown(band, choice.on)).length;
  // The legend always reads the newest row; hovering the chart moves only the reading beside it.
  const last = rows[rows.length - 1];
  const change = (update: (current: AgeChoice) => AgeChoice) => {
    setHover(null);
    setIsolate(null);
    setChoice(update);
  };

  return (
    <section
      className="wh-seller-panel"
      data-chart="agecohorts"
      aria-labelledby="wh-agecohorts"
    >
      <div className="wh-seller-head">
        <h3 id="wh-agecohorts">{title}</h3>
      </div>
      <Controls choice={choice} onChoice={change} text={text} />
      {last ? (
        <Plot
          rows={rows}
          choice={choice}
          formingT={formingT}
          isolate={isolate}
          label={text("seller.aria", { title })}
          hover={hover != null && hover < rows.length ? hover : null}
          onHover={setHover}
          text={text}
        />
      ) : (
        <p className="wh-muted">{text("seller.noData")}</p>
      )}
      <div className="wh-seller-legend">
        {bands.map((band, b) => (
          <button
            key={`${choice.detail}-${b}`}
            type="button"
            className="wh-ss-leg wh-seller-key"
            aria-pressed={isShown(band, choice.on)}
            title={text(choice.solo ? "agecohorts.pick" : "agecohorts.toggle")}
            onClick={() => change((current) => toggleBand(current, b))}
            onMouseEnter={() => setIsolate(b)}
            onMouseLeave={() => setIsolate(null)}
            onFocus={() => setIsolate(b)}
            onBlur={() => setIsolate(null)}
          >
            <i
              className="wh-seller-swatch"
              style={{ background: tone(choice.detail, b) }}
              aria-hidden="true"
            />
            {band.name}{" "}
            <b>
              {last
                ? legendValue(last, b, choice, text("sellside.off"))
                : isShown(band, choice.on)
                  ? "—"
                  : text("sellside.off")}
            </b>
          </button>
        ))}
      </div>
      {choice.scale === "pct" && shown < bands.length ? (
        <p className="wh-ss-note">
          {text(shown === 1 ? "agecohorts.visibleOne" : "agecohorts.visible", {
            n: shown,
          })}
        </p>
      ) : null}
      <div className="wh-seller-read">
        {(
          [
            ["seller.read.shows", "agecohorts.shows"],
            ["seller.read.implies", "agecohorts.implies"],
            ["seller.read.how", "agecohorts.how"],
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

export function AgeCohortChart() {
  const { text } = useWheelhouseText();
  const query = useQuery({
    queryKey: ["wh", "onchain", "age-cohorts"],
    queryFn: ({ signal }) => getAgeCohorts(signal),
    // The worker derives once an hour; polling more often only resends the same payload.
    refetchInterval: 300000,
    retry: false,
  });
  const data = query.data;

  // A failed request wins over older data: the chart must not look current when it is not.
  if (query.isError) {
    const failure = String(query.error.message ?? "");
    return (
      <div className="wh-seller wh-sellside wh-agec">
        <p className="wh-onchain-warn">{text("agecohorts.unavailable")}</p>
        {failure ? <p className="wh-muted">{failure}</p> : null}
      </div>
    );
  }
  if (!data)
    return (
      <div className="wh-seller wh-sellside wh-agec">
        <p className="wh-muted">{text("agecohorts.loading")}</p>
      </div>
    );

  const reasons = data.reasons.length ? (
    <p className="wh-muted">
      {data.reasons.map((reason) => reasonText(text, reason)).join(" · ")}
    </p>
  ) : null;
  if (data.data_state === "unavailable")
    return (
      <div className="wh-seller wh-sellside wh-agec">
        <p className="wh-onchain-warn">{text("agecohorts.unavailable")}</p>
        {reasons}
        {data.refreshing ? (
          <p role="status">{text("levels.refreshing")}</p>
        ) : null}
      </div>
    );

  const time = data.last_at ? utcStamp(Date.parse(data.last_at)) : "";
  const late = data.data_state === "delayed" || data.data_state === "stale";
  return (
    <div className="wh-seller wh-sellside wh-agec">
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
      {data.refreshing ? (
        <p role="status">{text("levels.refreshing")}</p>
      ) : null}
      {reasons}
      <Panel view={data} />
    </div>
  );
}

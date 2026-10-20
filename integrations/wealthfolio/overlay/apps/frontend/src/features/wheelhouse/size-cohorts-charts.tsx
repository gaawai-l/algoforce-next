import { useMemo, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSizeCohorts } from "./client";
import { ReadColumns } from "./flow-notes";
import { useWheelhouseText, type MessageKey } from "./i18n";
import { SIZE_WINDOWS, type SizeCohortsView, type WindowKey } from "./onchain-contract";
import { reasonText, rulesNote } from "./onchain-text";
import { useChartWidth } from "./seller-charts";
import { Segments } from "./sell-side-charts";
import {
  PNL_DEFAULT,
  SUPPLY_DEFAULT,
  axis,
  band,
  cohortRows,
  labelSpot,
  layout,
  nameAt,
  pnlLabel,
  pnlLegend,
  pnlPlot,
  pnlRead,
  rowName,
  supplyLabel,
  supplyLegend,
  supplyPlot,
  supplyRead,
  tickLabel,
  valueLabel,
  type Breakdown,
  type PlotRow,
  type PnlChoice,
  type Reading,
  type SupplyChoice,
} from "./size-cohorts";

const round = (value: number) => Math.round(value * 100) / 100;
const utcStamp = (t: number) => new Date(t).toISOString().slice(0, 16).replace("T", " ");

const BREAKDOWNS: readonly Breakdown[] = ["bands", "groups"];
const BREAKDOWN_NAMES = {
  bands: "sizes.bands",
  groups: "sizes.groups",
} as const satisfies Record<Breakdown, MessageKey>;
const SUPPLY_SCALES: readonly SupplyChoice["scale"][] = ["btc", "pct"];
const SUPPLY_UNITS = {
  btc: "sizes.btc",
  pct: "sizes.pctBand",
} as const satisfies Record<SupplyChoice["scale"], MessageKey>;
// Net before Gross, as the original's buttons (A:507-508).
const PNL_VIEWS: readonly PnlChoice["view"][] = ["net", "gross"];
const PNL_VIEW_NAMES = {
  net: "sizes.net",
  gross: "sizes.gross",
} as const satisfies Record<PnlChoice["view"], MessageKey>;
const PNL_SCALES: readonly PnlChoice["scale"][] = ["usd", "pct"];
const PNL_UNITS = {
  usd: "sizes.usd",
  pct: "sizes.pctCap",
} as const satisfies Record<PnlChoice["scale"], MessageKey>;
const SWATCHES = ["pos", "neg", "net"] as const;

interface DivergingBarsProps {
  rows: PlotRow[];
  rowLabel: (row: PlotRow) => string; // band or group name, already translated
  fmt: (v: number) => string; // value labels and tick labels (0 prints "0")
  gross: boolean; // labels parked at plotW + 12, a "net" header, net ticks
  selected: number | null; // index into rows
  onSelect: (index: number | null) => void;
  ariaLabel: string;
}

// Charts 5 and 6: a row a band or group, largest on top, bars out from a zero line in the middle
// of a symmetric axis (A:2064-2112, A:2245-2329). The pointer reads the row nearest it; the arrow
// keys walk the rows, Home and End jump to the ends and Escape clears the reading. With no bar to
// draw there is no axis either, only the rows' names and their "—".
function DivergingBars({
  rows,
  rowLabel,
  fmt,
  gross,
  selected,
  onSelect,
  ariaLabel,
}: DivergingBarsProps) {
  const { text } = useWheelhouseText();
  const [ref, width] = useChartWidth();
  const frame = layout(width, rows.length);
  const plotW = width - frame.left - frame.right;
  const plotH = frame.height - frame.top - frame.bottom;
  const { start, step, width: barH } = band(rows.length, plotH, frame.padding);
  const scale = axis(rows, frame.ticks);
  // The axis is symmetric, so 0 sits mid-plot even when there is none.
  const x = (v: number) =>
    round(scale ? ((v - scale.lo) / (scale.hi - scale.lo)) * plotW : plotW / 2);
  const rowTop = (i: number) => start + i * step;
  const middle = (i: number) => round(rowTop(i) + barH / 2 + 3.5);
  // Each row's name, on its bar's line when wide, 4px above the bar when compact.
  const nameX = nameAt(frame);
  const names = rows.map((row, i) => ({
    text: rowLabel(row),
    y: frame.compact ? round(rowTop(i) - 4) : middle(i),
  }));
  const last = rows.length - 1;
  // Between a row's top and the next row's top lies the gap the narrow layout writes its name in.
  const gap = step - barH;
  // Wide: the row whose bar's middle is nearest. Narrow: the row whose block (its name in the gap
  // above, then its bar) holds the pointer, as the read row's shade does.
  const at = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.height <= 0) return;
    const y = ((event.clientY - box.top) / box.height) * frame.height - frame.top;
    const row = frame.compact
      ? Math.floor((y - start + gap) / step)
      : Math.round((y - start - barH / 2) / step);
    onSelect(Math.min(last, Math.max(0, row)));
  };
  const key = (event: KeyboardEvent<SVGSVGElement>) => {
    const next: Record<string, number | null> = {
      ArrowDown: selected === null ? 0 : Math.min(last, selected + 1),
      ArrowUp: selected === null ? last : Math.max(0, selected - 1),
      Home: 0,
      End: last,
      Escape: null,
    };
    if (!(event.key in next)) return;
    event.preventDefault();
    onSelect(next[event.key]);
  };
  // The read row's shade: the whole band step, with the gap above it in the narrow layout, where
  // the row's name sits.
  return (
    <svg
      ref={ref}
      className="wh-seller-svg wh-sc-svg"
      viewBox={`0 0 ${width} ${frame.height}`}
      role="img"
      aria-label={ariaLabel}
      tabIndex={0}
      data-compact={frame.compact}
      onPointerMove={at}
      onPointerDown={at}
      onPointerLeave={(event) => {
        if (event.pointerType === "mouse") onSelect(null);
      }}
      onKeyDown={key}
      onBlur={() => onSelect(null)}
    >
      <g transform={`translate(${frame.left},${frame.top})`}>
        {selected !== null ? (
          <rect
            className="wh-sc-hover"
            x={-frame.left}
            y={round(rowTop(selected) - (frame.compact ? gap : gap / 2))}
            width={width}
            height={round(step)}
          />
        ) : null}
        {scale ? (
          <>
            {scale.ticks
              .filter((v) => v !== 0)
              .map((v) => (
                <line key={v} className="wh-sc-grid" x1={x(v)} x2={x(v)} y1={0} y2={plotH} />
              ))}
            {scale.ticks.map((v) => (
              <text
                key={v}
                className="wh-seller-tick"
                x={x(v)}
                y={plotH + 18}
                textAnchor="middle"
              >
                {tickLabel(v, fmt)}
              </text>
            ))}
          </>
        ) : null}
        {rows.map((row, i) => (
          <g key={row.key} data-row={row.key}>
            {row.bars.map((bar, j) => (
              <rect
                key={j}
                className={`wh-sc-bar wh-sc-bar--${bar.pos ? "pos" : "neg"}`}
                x={x(Math.min(0, bar.v))}
                y={round(rowTop(i))}
                width={round(Math.max(0.8, Math.abs(x(bar.v) - x(0))))}
                height={round(barH)}
              />
            ))}
            {gross && row.value !== null ? (
              <line
                className="wh-sc-tick"
                x1={x(row.value)}
                x2={x(row.value)}
                y1={round(rowTop(i) - 3)}
                y2={round(rowTop(i) + barH + 3)}
              />
            ) : null}
          </g>
        ))}
        {scale ? <line className="wh-sc-zero" x1={x(0)} x2={x(0)} y1={0} y2={plotH} /> : null}
        {rows.map((row, i) => {
          const label = valueLabel(row.value, fmt);
          const box = { plotW, gross, compact: frame.compact, left: frame.left };
          const spot = labelSpot(row.value, label, x, box, middle(i), names);
          return (
            <text
              key={row.key}
              className={spot.inside ? "wh-sc-val wh-sc-val--in" : "wh-sc-val"}
              x={round(spot.x)}
              y={middle(i)}
              textAnchor={spot.anchor}
            >
              {label}
            </text>
          );
        })}
        {rows.map((row, i) => (
          <text
            key={row.key}
            className="wh-sc-row"
            x={nameX.x}
            y={names[i].y}
            textAnchor={nameX.anchor}
          >
            {names[i].text}
          </text>
        ))}
        {gross ? (
          <text className="wh-sc-head" x={plotW + 12} y={-4} textAnchor="start">
            {text("sizes.pnl.netHead")}
          </text>
        ) : null}
      </g>
    </svg>
  );
}

// What a panel shows under its controls: the chart, a note when it has nothing to draw, the side
// captions, the legend, the reading of the picked row and the three notes. The reading names a
// row by its index in this plot, so a new plot (another choice, or new data) drops it.
function CohortPanel({
  chart,
  title,
  controls,
  plot,
  fmt,
  gross,
  win,
  noBlock,
  sides,
  legend,
  read,
  notes,
}: {
  chart: "supply" | "pnl";
  title: string;
  controls: ReactNode;
  plot: PlotRow[];
  fmt: (v: number) => string;
  gross: boolean;
  win: WindowKey;
  noBlock: boolean;
  sides: [string, string];
  legend: [MessageKey, string][];
  read: (index: number) => Reading;
  notes: { shows: MessageKey; implies: MessageKey; how: MessageKey };
}) {
  const { text } = useWheelhouseText();
  const [picked, setPicked] = useState<{ plot: PlotRow[]; index: number } | null>(null);
  const selected = picked !== null && picked.plot === plot ? picked.index : null;
  const reading = selected === null ? null : read(selected);
  const drawn = plot.some((row) => row.bars.length > 0);
  return (
    <section
      className="wh-seller-panel"
      data-chart={`sizes-${chart}`}
      aria-labelledby={`wh-sizes-${chart}`}
    >
      <div className="wh-seller-head">
        <h3 id={`wh-sizes-${chart}`}>{title}</h3>
      </div>
      <div className="wh-ss-controls">{controls}</div>
      {plot.length ? (
        <DivergingBars
          rows={plot}
          rowLabel={(row) => rowName(text, row.key)}
          fmt={fmt}
          gross={gross}
          selected={selected}
          onSelect={(index) =>
            setPicked((current) =>
              index === null
                ? null
                : current?.plot === plot && current.index === index
                  ? current
                  : { plot, index },
            )
          }
          ariaLabel={text("sizes.aria", { title })}
        />
      ) : null}
      {noBlock ? (
        <p className="wh-sc-note">{text("sizes.noBlock", { win })}</p>
      ) : !drawn ? (
        <p className="wh-sc-note">{text("seller.noData")}</p>
      ) : null}
      <p className="wh-sc-sides">
        <span>{sides[0]}</span>
        <span>{sides[1]}</span>
      </p>
      <div className="wh-seller-legend">
        {legend.map(([name, value], i) => (
          <span key={name} className="wh-seller-key">
            <i className={`wh-seller-swatch wh-sc-swatch--${SWATCHES[i]}`} aria-hidden="true" />
            {text(name)} <b>{value}</b>
          </span>
        ))}
      </div>
      <p className="wh-sc-read" aria-live="polite">
        {reading ? (
          <>
            <b>{reading.head}</b>
            {reading.lines.map(([name, value]) => (
              <span key={name}>
                {" · "}
                {text(name)} <b>{value}</b>
              </span>
            ))}
            {` · ${reading.foot}`}
          </>
        ) : (
          text("sizes.readHint")
        )}
      </p>
      <ReadColumns shows={notes.shows} implies={notes.implies} how={notes.how} />
    </section>
  );
}

function WindowControl({ value, onPick }: { value: WindowKey; onPick: (win: WindowKey) => void }) {
  const { text } = useWheelhouseText();
  return (
    <Segments
      label={text("sizes.window")}
      options={SIZE_WINDOWS}
      value={value}
      name={(win) => win}
      onPick={onPick}
    />
  );
}

function BreakdownControl({
  value,
  onPick,
}: {
  value: Breakdown;
  onPick: (group: Breakdown) => void;
}) {
  const { text } = useWheelhouseText();
  return (
    <Segments
      label={text("sizes.breakdown")}
      options={BREAKDOWNS}
      value={value}
      name={(group) => text(BREAKDOWN_NAMES[group])}
      onPick={onPick}
    />
  );
}

// Chart 5, Net Supply Change By Size Cohorts, with its own controls (the original's `sstate`).
function SupplyPanel({ view }: { view: SizeCohortsView }) {
  const { text } = useWheelhouseText();
  const [choice, setChoice] = useState<SupplyChoice>(SUPPLY_DEFAULT);
  const rows = useMemo(() => cohortRows(view, choice.group), [view, choice.group]);
  const plot = useMemo(() => supplyPlot(rows, choice), [rows, choice]);
  const change = (next: Partial<SupplyChoice>) => setChoice((current) => ({ ...current, ...next }));
  const unit = text(SUPPLY_UNITS[choice.scale]);
  const values = supplyLegend(rows, choice.win);
  return (
    <CohortPanel
      chart="supply"
      title={text("sizes.supply.title")}
      controls={
        <>
          <WindowControl value={choice.win} onPick={(win) => change({ win })} />
          <BreakdownControl value={choice.group} onPick={(group) => change({ group })} />
          <Segments
            label={text("sizes.scale")}
            options={SUPPLY_SCALES}
            value={choice.scale}
            name={(scale) => text(SUPPLY_UNITS[scale])}
            onPick={(scale) => change({ scale })}
          />
        </>
      }
      plot={plot}
      fmt={(v) => supplyLabel(v, choice.scale)}
      gross={false}
      win={choice.win}
      noBlock={view.no_block.includes(choice.win)}
      sides={[text("sizes.supply.left", { unit }), text("sizes.supply.right", { unit })]}
      legend={[
        ["sizes.supply.acc", values[0]],
        ["sizes.supply.dis", values[1]],
        ["sizes.supply.net", values[2]],
      ]}
      read={(index) => supplyRead(text, rows[index], choice.win)}
      notes={{
        shows: "sizes.supply.shows",
        implies: "sizes.supply.implies",
        how: "sizes.supply.how",
      }}
    />
  );
}

// Chart 6, Net Realized Profit & Loss By Size Cohorts, with its own controls (the original's
// `plstate`).
function PnlPanel({ view }: { view: SizeCohortsView }) {
  const { text } = useWheelhouseText();
  const [choice, setChoice] = useState<PnlChoice>(PNL_DEFAULT);
  const rows = useMemo(() => cohortRows(view, choice.group), [view, choice.group]);
  const plot = useMemo(() => pnlPlot(rows, choice), [rows, choice]);
  const change = (next: Partial<PnlChoice>) => setChoice((current) => ({ ...current, ...next }));
  const unit = text(PNL_UNITS[choice.scale]);
  const gross = choice.view === "gross";
  const values = pnlLegend(rows, choice.win);
  return (
    <CohortPanel
      chart="pnl"
      title={text("sizes.pnl.title")}
      controls={
        <>
          <WindowControl value={choice.win} onPick={(win) => change({ win })} />
          <BreakdownControl value={choice.group} onPick={(group) => change({ group })} />
          <Segments
            label={text("sizes.view")}
            options={PNL_VIEWS}
            value={choice.view}
            name={(item) => text(PNL_VIEW_NAMES[item])}
            onPick={(item) => change({ view: item })}
          />
          <Segments
            label={text("sizes.scale")}
            options={PNL_SCALES}
            value={choice.scale}
            name={(scale) => text(PNL_UNITS[scale])}
            onPick={(scale) => change({ scale })}
          />
        </>
      }
      plot={plot}
      fmt={(v) => pnlLabel(v, choice.scale)}
      gross={gross}
      win={choice.win}
      noBlock={view.no_block.includes(choice.win)}
      sides={[
        text(gross ? "sizes.pnl.left.gross" : "sizes.pnl.left.net", { unit }),
        text(gross ? "sizes.pnl.right.gross" : "sizes.pnl.right.net", { unit }),
      ]}
      legend={[
        ["sizes.pnl.profit", values[0]],
        ["sizes.pnl.loss", values[1]],
        ["sizes.pnl.net", values[2]],
      ]}
      read={(index) => pnlRead(text, rows[index], choice.win)}
      notes={{ shows: "sizes.pnl.shows", implies: "sizes.pnl.implies", how: "sizes.pnl.how" }}
    />
  );
}

// The Size cohorts flow: Charts 5 and 6 over the twelve wallet-size bands the service derives
// each hour, with the freshness of the hour they were read at.
export function SizeCohortsCharts() {
  const { text } = useWheelhouseText();
  const query = useQuery({
    queryKey: ["wh", "onchain", "size-cohorts"],
    queryFn: ({ signal }) => getSizeCohorts(signal),
    // The worker derives once an hour; polling more often only resends the same payload.
    refetchInterval: 300000,
    retry: false,
  });
  const data = query.data;

  // A failed request wins over older data: the charts must not look current when they are not.
  if (query.isError) {
    const failure = String(query.error.message ?? "");
    return (
      <div className="wh-seller wh-sizes">
        <p className="wh-onchain-warn">{text("sizes.unavailable")}</p>
        {failure ? <p className="wh-muted">{failure}</p> : null}
      </div>
    );
  }
  if (!data)
    return (
      <div className="wh-seller wh-sizes">
        <p className="wh-muted">{text("sizes.loading")}</p>
      </div>
    );

  const reasons = data.reasons.length ? (
    <p className="wh-muted">{data.reasons.map((reason) => reasonText(text, reason)).join(" · ")}</p>
  ) : null;
  if (data.data_state === "unavailable")
    return (
      <div className="wh-seller wh-sizes">
        <p className="wh-onchain-warn">{text("sizes.unavailable")}</p>
        {reasons}
        {data.refreshing ? <p role="status">{text("levels.refreshing")}</p> : null}
      </div>
    );

  const time = data.last_at ? utcStamp(Date.parse(data.last_at)) : "";
  const late = data.data_state === "delayed" || data.data_state === "stale";
  return (
    <div className="wh-seller wh-sizes">
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
          {text(data.data_state === "delayed" ? "seller.delayed" : "seller.stale", {
            time: time || text("missing"),
          })}
        </p>
      ) : null}
      {data.refreshing ? <p role="status">{text("levels.refreshing")}</p> : null}
      {reasons}
      <SupplyPanel view={data} />
      <PnlPanel view={data} />
    </div>
  );
}

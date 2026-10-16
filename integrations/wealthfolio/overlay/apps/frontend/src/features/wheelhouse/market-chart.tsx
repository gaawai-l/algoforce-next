import { useEffect, useMemo, useRef, useState } from "react";
import type { Analysis } from "./client";
import { money, stamp } from "./client";
import type { DemarkSequence } from "./demark-contract";
import { labeled, useWheelhouseText } from "./i18n";
import { visibleWindow, type RangeChoice, type BarWindow } from "./chart-range";
import { ChartRangeNavigator } from "./chart-range-navigator";

interface ChartProps {
  analysis: Analysis;
  visibleBars: number;
  showLevels: boolean;
  showDemark?: boolean;
  sequence?: DemarkSequence;
}

export function MarketChart({
  analysis,
  visibleBars,
  showLevels,
  showDemark = false,
  sequence,
}: ChartProps) {
  const { text } = useWheelhouseText();
  const missing = text("missing");
  const [selected, setSelected] = useState<number | null>(null);
  const [rangeChoice, setRangeChoice] = useState<RangeChoice | null>(null);
  useEffect(() => {
    setRangeChoice(null);
    setSelected(null);
  }, [visibleBars]);
  const chartRef = useRef<SVGSVGElement>(null);
  const [chartWidth, setChartWidth] = useState(980);
  const [chartHeight, setChartHeight] = useState(540);
  const window = visibleWindow(
    analysis.bars,
    analysis.stream.timeframe,
    chartWidth - 128,
    visibleBars,
    rangeChoice,
  );
  const bars = analysis.bars.slice(window.start, window.end + 1);
  const points = analysis.points.slice(window.start, window.end + 1);
  const changeRange = (range: BarWindow) => {
    setSelected(null);
    setRangeChoice({
      kind: "custom",
      from: analysis.bars[range.start].bar.open_time,
      to: analysis.bars[range.end].bar.close_time,
    });
  };
  const rangeToolbar = (
    <div
      className="wh-range-toolbar"
      role="group"
      aria-label={text("range.navigator")}
    >
      <button
        type="button"
        aria-pressed={rangeChoice?.kind === "week"}
        onClick={() => {
          setRangeChoice({ kind: "week" });
          setSelected(null);
        }}
      >
        {text("range.week")}
      </button>
      <button
        type="button"
        aria-pressed={rangeChoice?.kind === "friday"}
        title={text("range.fridayHint")}
        onClick={() => {
          setRangeChoice({ kind: "friday" });
          setSelected(null);
        }}
      >
        {text("range.friday")}
      </button>
      <button
        type="button"
        aria-pressed={
          rangeChoice?.kind === "all" || (!rangeChoice && visibleBars === -1)
        }
        onClick={() => {
          setRangeChoice({ kind: "all" });
          setSelected(null);
        }}
      >
        {text("range.all")}
      </button>
      <button
        type="button"
        onClick={() => {
          setRangeChoice(null);
          setSelected(null);
        }}
      >
        {text("range.reset")}
      </button>
      <span>
        {text("range.visible", {
          visible: bars.length,
          total: analysis.bars.length,
        })}
      </span>
    </div>
  );
  useEffect(() => {
    if (!chartRef.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width && width > 0) setChartWidth(Math.round(width));
      const height = entries[0]?.contentRect.height;
      if (height && height > 0) setChartHeight(Math.round(height));
    });
    observer.observe(chartRef.current);
    return () => observer.disconnect();
  }, [bars.length]);
  const plotWidth = Math.max(120, chartWidth - 128);
  const right = 16 + plotWidth;
  const eventsByBar = useMemo(() => {
    const index = new Map<string, NonNullable<Analysis["demark"]>["events"]>();
    for (const event of analysis.demark?.events ?? []) {
      const row = index.get(event.bar.revision_id) ?? [];
      row.push(event);
      index.set(event.bar.revision_id, row);
    }
    return index;
  }, [analysis.demark]);
  if (!bars.length)
    return (
      <>
        {rangeToolbar}
        <div className="wh-empty">{text("range.empty")}</div>
      </>
    );
  const latest = points.at(-1);
  const visibleStart = new Date(bars[0].bar.close_time).getTime();
  const visibleEnd = new Date(bars[bars.length - 1].bar.close_time).getTime();
  const ended = analysis.demark?.events.find(
    (e) =>
      e.sequence_id === sequence?.sequence_id &&
      ["cancelled", "recycled", "continuity_lost"].includes(e.kind),
  )?.bar.close_time;
  const tdstAt =
    sequence?.setup_status === "completed"
      ? sequence.setup_bars[8].close_time
      : null;
  const tdstEnd = sequence?.tdst_breached_at ?? ended;
  const tdst =
    showDemark &&
    sequence?.tdst != null &&
    tdstAt &&
    new Date(tdstAt).getTime() <= visibleEnd &&
    (!tdstEnd || new Date(tdstEnd).getTime() >= visibleStart)
      ? Number(sequence.tdst)
      : null;
  const risk =
    showDemark &&
    sequence?.risk_status === "valid" &&
    sequence.risk_level != null &&
    sequence.qualified_at &&
    new Date(sequence.qualified_at).getTime() <= visibleEnd
      ? Number(sequence.risk_level)
      : null;
  const visibleIndex = (at: string | null | undefined) => {
    if (!at) return bars.length - 1;
    const found = bars.findIndex(
      (b) => new Date(b.bar.close_time).getTime() >= new Date(at).getTime(),
    );
    return found < 0 ? bars.length - 1 : found;
  };
  const values = bars.flatMap((row) => [
    Number(row.bar.high),
    Number(row.bar.low),
  ]);
  points.forEach((p) => {
    if (!showDemark && p.sma !== null) values.push(Number(p.sma));
  });
  if (showLevels && latest?.prior_high != null)
    values.push(Number(latest.prior_high));
  if (showLevels && latest?.prior_low != null)
    values.push(Number(latest.prior_low));
  if (tdst !== null) values.push(tdst);
  if (risk !== null) values.push(risk);
  const low = Math.min(...values),
    high = Math.max(...values);
  const padding = Math.max((high - low) * 0.1, high * 0.0001);
  const top = high + padding,
    bottom = low - padding;
  const x = (i: number) => 16 + ((i + 0.5) * plotWidth) / bars.length;
  const plotBottom = chartHeight - 47;
  const y = (price: number) =>
    18 + ((top - price) / (top - bottom)) * (plotBottom - 18);
  const barWidth = Math.max(1, (plotWidth / bars.length) * 0.65);
  const index =
    selected === null ? bars.length - 1 : Math.min(selected, bars.length - 1);
  const current = bars[index].bar;
  const selectedEvents = showDemark
    ? (eventsByBar.get(bars[index].revision_id) ?? [])
    : [];

  const segments: string[] = [];
  let continuous = false;
  points.forEach((point, i) => {
    if (point.sma === null) {
      continuous = false;
      return;
    }
    segments.push(`${continuous ? "L" : "M"}${x(i)},${y(Number(point.sma))}`);
    continuous = true;
  });
  return (
    <>
      {rangeToolbar}
      {window.clipped && (
        <p className="wh-range-notice">{text("range.clipped")}</p>
      )}
      <div className="wh-chart-readout">
        {stamp(current.open_time, missing)} · O {money(current.open, missing)} ·
        H {money(current.high, missing)} · L {money(current.low, missing)} · C{" "}
        {money(current.close, missing)}
      </div>
      {showDemark && (
        <div className="wh-chart-readout" aria-live="polite">
          {!analysis.demark
            ? text("chart.notCalculated")
            : selectedEvents.length
              ? selectedEvents
                  .map(
                    (e) =>
                      `${labeled(text, "side", e.side)} ${labeled(text, "kind", e.kind)}${e.count !== null ? ` ${e.count}` : ""}`,
                  )
                  .join(" · ")
              : text("chart.noEvent")}
        </div>
      )}
      <svg
        className="wh-chart"
        ref={chartRef}
        viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        role="img"
        aria-label={
          showDemark
            ? text("chart.ariaDemark", {
                symbol: analysis.stream.symbol,
                timeframe: analysis.stream.timeframe,
              })
            : text("chart.ariaSma", {
                symbol: analysis.stream.symbol,
                timeframe: analysis.stream.timeframe,
                window: analysis.rules.window,
              })
        }
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            setSelected(
              Math.max(
                0,
                Math.min(
                  bars.length - 1,
                  index + (event.key === "ArrowRight" ? 1 : -1),
                ),
              ),
            );
          }
        }}
        onPointerMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setSelected(
            Math.max(
              0,
              Math.min(
                bars.length - 1,
                Math.floor(
                  ((((event.clientX - rect.left) / rect.width) * chartWidth -
                    16) /
                    plotWidth) *
                    bars.length,
                ),
              ),
            ),
          );
        }}
        onPointerLeave={() => setSelected(null)}
      >
        <title>
          {showDemark ? text("chart.titleDemark") : text("chart.titleSma")}
        </title>
        {Array.from({ length: 5 }, (_, i) => {
          const price = bottom + ((top - bottom) * i) / 4;
          return (
            <g key={i}>
              <line
                x1="16"
                x2={right}
                y1={y(price)}
                y2={y(price)}
                stroke="var(--wh-edge)"
              />
              <text x={right + 11} y={y(price) + 4} className="wh-axis">
                {money(String(price), missing)}
              </text>
            </g>
          );
        })}
        {bars.map((row, i) => {
          const b = row.bar;
          const up = Number(b.close) >= Number(b.open);
          return (
            <g
              key={row.revision_id}
              stroke={up ? "var(--wh-cyan)" : "var(--wh-rose)"}
              fill={up ? "var(--wh-cyan)" : "var(--wh-rose)"}
            >
              <line
                x1={x(i)}
                x2={x(i)}
                y1={y(Number(b.high))}
                y2={y(Number(b.low))}
              />
              <rect
                x={x(i) - barWidth / 2}
                y={Math.min(y(Number(b.open)), y(Number(b.close)))}
                width={barWidth}
                height={Math.max(
                  1,
                  Math.abs(y(Number(b.open)) - y(Number(b.close))),
                )}
              />
            </g>
          );
        })}
        {!showDemark && (
          <path
            d={segments.join(" ")}
            stroke="var(--wh-violet)"
            fill="none"
            strokeWidth="1.7"
          />
        )}
        {showDemark &&
          bars.map((row, i) => {
            const events = (eventsByBar.get(row.revision_id) ?? []).filter(
              (e) =>
                ["setup_completed", "qualified13", "deferred13"].includes(
                  e.kind,
                ),
            );
            return (["buy", "sell"] as const).map((side) => {
              const atSide = events.filter((e) => e.side === side);
              if (!atSide.length) return null;
              const label = [
                ...new Set(
                  atSide.map((e) =>
                    e.kind === "qualified13"
                      ? "13"
                      : e.kind === "setup_completed"
                        ? "9"
                        : "+",
                  ),
                ),
              ].join("/");
              return (
                <text
                  key={`${row.revision_id}-${side}`}
                  x={x(i)}
                  y={
                    side === "buy"
                      ? Math.min(chartHeight - 34, y(Number(row.bar.low)) + 16)
                      : Math.max(13, y(Number(row.bar.high)) - 8)
                  }
                  textAnchor="middle"
                  className={`wh-td-marker ${atSide.some((e) => e.kind === "qualified13") ? "wh-td-thirteen" : atSide.some((e) => e.kind === "setup_completed") ? "wh-td-nine" : "wh-td-deferred"}`}
                >
                  <title>
                    {labeled(text, "side", side)} {label} ·{" "}
                    {stamp(row.bar.close_time, missing)}
                  </title>
                  {side === "buy" ? "B" : "S"}
                  {label}
                </text>
              );
            });
          })}
        {tdst !== null && (
          <g>
            <line
              x1={x(visibleIndex(tdstAt))}
              x2={x(visibleIndex(tdstEnd))}
              y1={y(tdst)}
              y2={y(tdst)}
              stroke="var(--wh-violet)"
              strokeDasharray="6 4"
            />
            <text
              x={Math.min(x(visibleIndex(tdstAt)), right - 130)}
              y={y(tdst) - 5}
              className="wh-axis"
            >
              TDST{tdstEnd ? " · historical" : ""}
            </text>
          </g>
        )}
        {risk !== null && (
          <g>
            <line
              x1={x(visibleIndex(sequence?.qualified_at))}
              x2={right}
              y1={y(risk)}
              y2={y(risk)}
              stroke="var(--wh-rose)"
              strokeDasharray="2 4"
            />
            <text
              x={Math.min(x(visibleIndex(sequence?.qualified_at)), right - 130)}
              y={y(risk) - 5}
              className="wh-axis"
            >
              Risk Level · valid
            </text>
          </g>
        )}
        {showLevels && latest?.prior_high && (
          <line
            x1="16"
            x2={right}
            y1={y(Number(latest.prior_high))}
            y2={y(Number(latest.prior_high))}
            stroke="var(--wh-rose)"
            strokeDasharray="5 5"
          />
        )}
        {showLevels && latest?.prior_low && (
          <line
            x1="16"
            x2={right}
            y1={y(Number(latest.prior_low))}
            y2={y(Number(latest.prior_low))}
            stroke="var(--wh-cyan)"
            strokeDasharray="5 5"
          />
        )}
        <line
          x1={x(index)}
          x2={x(index)}
          y1="18"
          y2={plotBottom}
          stroke="var(--wh-muted)"
          strokeDasharray="2 4"
          opacity=".5"
        />
        <text x="16" y={chartHeight - 18} className="wh-axis">
          {chartWidth < 500
            ? stamp(bars[0].bar.open_time, missing).slice(5, 10)
            : stamp(bars[0].bar.open_time, missing).slice(0, 16)}
        </text>
        <text
          x={right}
          y={chartHeight - 18}
          textAnchor="end"
          className="wh-axis"
        >
          {chartWidth < 500
            ? stamp(bars.at(-1)?.bar.open_time, missing).slice(5, 10)
            : stamp(bars.at(-1)?.bar.open_time, missing).slice(0, 16)}{" "}
          UTC
        </text>
      </svg>
      <ChartRangeNavigator
        total={analysis.bars.length}
        start={window.start}
        end={window.end}
        onChange={changeRange}
      />
      <div className="wh-range-dates" aria-live="polite">
        <span>{stamp(bars[0].bar.open_time, missing)}</span>
        <span>→ {stamp(bars.at(-1)?.bar.close_time, missing)}</span>
      </div>
      <div className="wh-chart-legend">
        {showDemark ? (
          <>
            <span>{text("legend.buySell")}</span>
            <span className="wh-td-nine">{text("legend.setup")}</span>
            <span className="wh-td-thirteen">{text("legend.qualified")}</span>
            <span className="wh-td-deferred">{text("legend.deferred")}</span>
            <span>{text("legend.lines")}</span>
          </>
        ) : (
          <>
            <span className="wh-purple">
              {text("legend.sma", { window: analysis.rules.window })}
            </span>
            <span>{text("legend.dashed")}</span>
          </>
        )}
        <span>{text("legend.closedOnly")}</span>
      </div>
    </>
  );
}

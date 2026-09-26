import { useState } from "react";
import type { Analysis } from "./client";
import { money, stamp } from "./client";

interface ChartProps {
  analysis: Analysis;
  visibleBars: number;
  showLevels: boolean;
}

export function MarketChart({ analysis, visibleBars, showLevels }: ChartProps) {
  const [selected, setSelected] = useState<number | null>(null);
  const bars = analysis.bars.slice(-visibleBars);
  const points = analysis.points.slice(-visibleBars);
  if (!bars.length)
    return (
      <div className="wh-empty">
        No closed bars were available at both cutoffs.
      </div>
    );
  const latest = points.at(-1);
  const values = bars.flatMap((row) => [
    Number(row.bar.high),
    Number(row.bar.low),
  ]);
  points.forEach((p) => {
    if (p.sma !== null) values.push(Number(p.sma));
  });
  if (showLevels && latest?.prior_high != null)
    values.push(Number(latest.prior_high));
  if (showLevels && latest?.prior_low != null)
    values.push(Number(latest.prior_low));
  const low = Math.min(...values),
    high = Math.max(...values);
  const padding = Math.max((high - low) * 0.1, high * 0.0001);
  const top = high + padding,
    bottom = low - padding;
  const x = (i: number) => 16 + ((i + 0.5) * 850) / bars.length;
  const y = (price: number) => 18 + ((top - price) / (top - bottom)) * 310;
  const barWidth = Math.max(1, (850 / bars.length) * 0.65);
  const index =
    selected === null ? bars.length - 1 : Math.min(selected, bars.length - 1);
  const current = bars[index].bar;
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
      <div className="wh-chart-readout">
        {stamp(current.open_time)} · O {money(current.open)} · H{" "}
        {money(current.high)} · L {money(current.low)} · C{" "}
        {money(current.close)}
      </div>
      <svg
        className="wh-chart"
        viewBox="0 0 980 375"
        role="img"
        aria-label={`${analysis.stream.symbol} ${analysis.stream.timeframe} closed candlesticks and SMA ${analysis.rules.window}. Use arrow keys to inspect bars; a data table is available below.`}
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
                  ((((event.clientX - rect.left) / rect.width) * 980 - 16) /
                    850) *
                    bars.length,
                ),
              ),
            ),
          );
        }}
        onPointerLeave={() => setSelected(null)}
      >
        <title>
          Closed OHLC bars and server-calculated SMA. No trading signal.
        </title>
        {Array.from({ length: 5 }, (_, i) => {
          const price = bottom + ((top - bottom) * i) / 4;
          return (
            <g key={i}>
              <line
                x1="16"
                x2="866"
                y1={y(price)}
                y2={y(price)}
                stroke="var(--wh-edge)"
              />
              <text x="877" y={y(price) + 4} className="wh-axis">
                {money(String(price))}
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
        <path
          d={segments.join(" ")}
          stroke="var(--wh-violet)"
          fill="none"
          strokeWidth="1.7"
        />
        {showLevels && latest?.prior_high && (
          <line
            x1="16"
            x2="866"
            y1={y(Number(latest.prior_high))}
            y2={y(Number(latest.prior_high))}
            stroke="var(--wh-rose)"
            strokeDasharray="5 5"
          />
        )}
        {showLevels && latest?.prior_low && (
          <line
            x1="16"
            x2="866"
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
          y2="330"
          stroke="var(--wh-muted)"
          strokeDasharray="2 4"
          opacity=".5"
        />
        <text x="16" y="357" className="wh-axis">
          {stamp(bars[0].bar.open_time).slice(0, 16)}
        </text>
        <text x="866" y="357" textAnchor="end" className="wh-axis">
          {stamp(bars.at(-1)?.bar.open_time).slice(0, 16)} UTC
        </text>
      </svg>
      <div className="wh-chart-legend">
        <span className="wh-purple">— SMA {analysis.rules.window}</span>
        <span>Dashed: prior-window high / low</span>
        <span>Closed bars only</span>
      </div>
    </>
  );
}

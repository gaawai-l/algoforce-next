import { useRef } from "react";
import type { BarWindow } from "./chart-range";
import { useWheelhouseText } from "./i18n";

export function ChartRangeNavigator({
  total,
  start,
  end,
  onChange,
}: {
  total: number;
  start: number;
  end: number;
  onChange: (range: BarWindow) => void;
}) {
  const { text } = useWheelhouseText();
  const track = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; start: number; end: number } | null>(null);
  if (total < 2) return null;
  const max = total - 1;
  const move = (offset: number, origin = { start, end }) => {
    const length = origin.end - origin.start;
    const next = Math.max(0, Math.min(max - length, origin.start + offset));
    onChange({ start: next, end: next + length });
  };
  return (
    <div
      className="wh-range-navigator"
      role="group"
      aria-label={text("range.navigator")}
    >
      <button
        type="button"
        aria-label={text("range.earlier")}
        disabled={start <= 0}
        onClick={() => move(-Math.max(1, Math.round((end - start + 1) / 2)))}
      >
        ‹
      </button>
      <div className="wh-range-track" ref={track}>
        <button
          type="button"
          className="wh-range-window"
          aria-label={text("range.pan")}
          style={{
            left: `${(start / max) * 100}%`,
            width: `${((end - start) / max) * 100}%`,
          }}
          onPointerDown={(e) => {
            e.preventDefault();
            e.currentTarget.setPointerCapture(e.pointerId);
            drag.current = { x: e.clientX, start, end };
          }}
          onPointerMove={(e) => {
            if (drag.current && track.current)
              move(
                Math.round(
                  ((e.clientX - drag.current.x) / track.current.clientWidth) *
                    max,
                ),
                drag.current,
              );
          }}
          onPointerUp={(e) => {
            drag.current = null;
            e.currentTarget.releasePointerCapture(e.pointerId);
          }}
          onPointerCancel={() => {
            drag.current = null;
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
              e.preventDefault();
              move(e.key === "ArrowLeft" ? -1 : 1);
            }
          }}
        />
        <input
          type="range"
          aria-label={text("range.start")}
          min={0}
          max={max}
          value={start}
          onChange={(e) =>
            onChange({ start: Math.min(Number(e.target.value), end - 1), end })
          }
        />
        <input
          type="range"
          aria-label={text("range.end")}
          min={0}
          max={max}
          value={end}
          onChange={(e) =>
            onChange({
              start,
              end: Math.max(Number(e.target.value), start + 1),
            })
          }
        />
      </div>
      <button
        type="button"
        aria-label={text("range.later")}
        disabled={end >= max}
        onClick={() => move(Math.max(1, Math.round((end - start + 1) / 2)))}
      >
        ›
      </button>
    </div>
  );
}

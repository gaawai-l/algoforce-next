import { useCallback, useEffect, useRef, useState } from "react";
import { usd } from "./client";
import { useWheelhouseText, type TextFn } from "./i18n";

// One cost-basis peak drawn on the price rail, from `low` to `high` around its `price`.
export interface RailBand {
  id: string; // "sth-1"
  cohort: "sth" | "lth";
  index: number; // K number, 1-based
  price: number;
  low: number; // price - width / 2
  high: number; // price + width / 2
  strength: number; // 0..1
  btc: number;
  share: number;
}

interface RailProps {
  bands: RailBand[]; // in list order: cohort, then K number
  y: (price: number) => number;
  top: number;
  bottom: number;
  x: number;
  width: number;
  plotLeft: number;
  plotRight: number;
  onActive: (band: RailBand | null) => void;
}

// The rail follows the chart's own width, not the viewport.
export const railWidth = (chartWidth: number) => (chartWidth < 600 ? 16 : 28);

const LANE = { sth: 0, lth: 1 } as const;

const bandName = (band: RailBand) =>
  `${band.cohort.toUpperCase()} K${band.index}`;

const btcAmount = new Intl.NumberFormat("en-US", {
  notation: "compact",
  maximumSignificantDigits: 3,
});

export const bandReadout = (text: TextFn, band: RailBand) =>
  text("rail.readout", {
    band: bandName(band),
    price: usd(band.price),
    width: usd(band.high - band.low),
    btc: btcAmount.format(band.btc),
    share: `${(band.share * 100).toFixed(1)}%`,
    strength: `${Math.round(band.strength * 100)}%`,
  });

export function LevelsRail({
  bands,
  y,
  top,
  bottom,
  x,
  width,
  plotLeft,
  plotRight,
  onActive,
}: RailProps) {
  const { text } = useWheelhouseText();
  const [active, setActive] = useState<string | null>(null);
  // The latest callback, so the unmount report below reaches the current chart.
  const report = useRef(onActive);
  useEffect(() => {
    report.current = onActive;
  });
  const activate = useCallback((band: RailBand | null) => {
    setActive(band?.id ?? null);
    report.current(band);
  }, []);
  const laneWidth = width / 2 - 1;
  // Only the part inside the price range is drawn; the rail never widens the y-axis.
  const drawn = bands
    .filter((band) => band.high > bottom && band.low < top)
    .map((band, i) => {
      const y1 = y(Math.min(band.high, top));
      return {
        band,
        // The band's place in the list, which the paint order below no longer follows.
        position: i + 1,
        x: x + 1 + (band.cohort === "lth" ? width / 2 : 0),
        width: 2 + band.strength * (laneWidth - 2),
        y: y1,
        height: y(Math.max(band.low, bottom)) - y1,
      };
    })
    // SVG paints in DOM order: within a lane the widest band goes first, so every narrower one
    // sits on top of it and keeps a visible, hoverable strip.
    .sort(
      (a, b) =>
        LANE[a.band.cohort] - LANE[b.band.cohort] ||
        b.band.strength - a.band.strength ||
        a.band.price - b.band.price,
    );
  const spread = drawn.find((d) => d.band.id === active);
  // A refresh can remove the active band or move it out of range; drop it so the chart's
  // read-out never keeps showing a band that is no longer drawn.
  const gone = active !== null && !spread;
  useEffect(() => {
    if (gone) activate(null);
  }, [gone, activate]);
  // Unmounting (a method switch, an empty range) must not leave the read-out on a band either.
  useEffect(() => () => report.current(null), []);
  return (
    <g role="list" aria-label={text("rail.list")}>
      {spread && (
        <rect
          className={`wh-rail-spread is-${spread.band.cohort}`}
          aria-hidden="true"
          x={plotLeft}
          width={plotRight - plotLeft}
          y={spread.y}
          height={spread.height}
        />
      )}
      <rect
        className="wh-rail-track"
        aria-hidden="true"
        x={x}
        width={width}
        y={y(top)}
        height={y(bottom) - y(top)}
      />
      {drawn.map(({ band, position, ...box }) => (
        <rect
          key={band.id}
          className={`wh-rail-band is-${band.cohort}`}
          role="listitem"
          tabIndex={0}
          aria-label={`${bandName(band)} · ${usd(band.price)}`}
          aria-posinset={position}
          aria-setsize={drawn.length}
          {...box}
          onPointerEnter={() => activate(band)}
          onPointerLeave={() => activate(null)}
          onFocus={() => activate(band)}
          onBlur={() => activate(null)}
          // Arrow keys on a band must not move the chart's selected bar.
          onKeyDown={(event) => event.stopPropagation()}
        />
      ))}
      {spread && (
        // Drawn last, so the focus and hover cue is never under another band.
        <rect
          className="wh-rail-active"
          aria-hidden="true"
          x={spread.x}
          width={spread.width}
          y={spread.y}
          height={spread.height}
        />
      )}
    </g>
  );
}
